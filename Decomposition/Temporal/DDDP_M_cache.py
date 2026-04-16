import os
import math
import time
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from Build_Model.store import *
from Build_Model.store import store_results
from Build_Model.Constraints import build_pyomo_model

# =========================================================
# MODEL CACHE - Build once, reuse many times
# =========================================================
MODEL_CACHE = {}  # {stage_idx: model}

def get_or_build_stage(stage_idx, data, obj, non_linear=False, p_control=False, integer=False,single_battery_variable=False):
    """Get cached model or build new one. Also creates persistent solver."""
    global MODEL_CACHE

    cache_key = (int(stage_idx), bool(non_linear), bool(p_control), bool(integer),bool(single_battery_variable))

    if cache_key not in MODEL_CACHE:
        MODEL_CACHE[cache_key] = build_pyomo_model(data,obj, stage_idx, non_linear=non_linear, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)

    return MODEL_CACHE[cache_key]

# =========================================================
# SDDP solve_stage with cuts
# =========================================================
def solve_stage(stage_idx, prev_stage_B, cuts_future, data, obj, solver,alpha_scd=1e-3,non_linear=False, p_control=False, integer=False,single_battery_variable=False):
    m = get_or_build_stage(stage_idx, data, obj, non_linear=non_linear, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
    t = stage_idx

    for j in m.Bset:
        m.prev_B[j].set_value(prev_stage_B[j])

    # Add new cuts (only add cuts not already in model)
    current_num_cuts = len(m.cuts)
    if len(cuts_future) > current_num_cuts:
        for i in range(current_num_cuts, len(cuts_future)):
            alpha, beta = cuts_future[i]
            m.cuts.add(m.theta >= alpha + sum(beta[j] * m.B[t, j] for j in m.Bset))

    # Solve with non-persistent solver
    opt = SolverFactory(solver)
    # opt.options['NonConvex'] = 2
    # opt.options['OutputFlag'] = 0
    opt.solve(m, tee=False)

    # Extract results
    beta = {j: m.dual[m.battery_dynamics[t, j]] for j in m.Bset}
    Q = value(m.obj)
    S_obj = value(m.stage_cost)
    B_end = {j: value(m.B[t, j]) for j in m.Bset}
    # print(f"Stage {stage_idx} solved with Q={Q:.4f}")
    return Q, beta, B_end, S_obj


def dddp_solve(data, obj, solver='gurobi',alpha_scd=1e-3,max_iters=50, tol=1e-4, *, non_linear=False, p_control=False, integer=False,single_battery_variable=False):
    global MODEL_CACHE
    MODEL_CACHE.clear()

    time_periods = sorted([int(x) for x in list(data['Tset'])])
    num_stages = len(time_periods)
    Bset = list(data['Bset'])

    # Pre-build all stage models (one-time cost)
    print("Building cached models for all stages...")
    for stage_idx in range(1, num_stages + 1):
        MODEL_CACHE[(int(stage_idx), bool(non_linear), bool(p_control), bool(integer),bool(single_battery_variable))] = get_or_build_stage(stage_idx, data, obj, non_linear=non_linear, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
    print(f"Built {num_stages} cached models.")

    # Cuts storage: cuts[stage] = list of (alpha, beta) tuples
    cuts = {f'cuts_{i}': [] for i in range(1, num_stages)}

    initial_b = data['b0']
    prev_LB = 0
    start_time = time.perf_counter()
    LB_container = []
    UB_container = []

    for k in range(1, max_iters + 1):
        stage_results = {}
        total_obj_value = 0

        # FORWARD PASS
        for stage_idx in range(1, num_stages+1):
            prev_B = initial_b if stage_idx == 1 else stage_results[stage_idx-1]["B_end"]

            Q, beta, B_end, stage_obj = solve_stage(
                stage_idx, prev_B, cuts.get(f'cuts_{stage_idx}', []),
                data,
                obj,
                solver=solver,
                alpha_scd=alpha_scd,
                non_linear=non_linear, p_control=p_control, integer=integer,
                single_battery_variable=single_battery_variable
            )
            stage_results[stage_idx] = {"Q": Q, "beta": beta, "B_end": B_end, "stage_obj": stage_obj}
            total_obj_value += stage_obj

        # BACKWARD PASS - compute expected cuts
        for stage_idx in range(num_stages, 1, -1):
            beta_exp = {j: 0.0 for j in Bset}
            Q_exp = 0.0
            prev_B = stage_results[stage_idx-1]["B_end"]
            Q_s, beta_s, _, _ = solve_stage(
                stage_idx,
                prev_B,
                cuts.get(f'cuts_{stage_idx}', []),
                data,
                obj,
                solver=solver,
                alpha_scd=alpha_scd,
                non_linear=non_linear, p_control=p_control, integer=integer,
                single_battery_variable=single_battery_variable
            )

            Q_exp = Q_s
            for j in Bset:
                beta_exp[j] = beta_s[j]

            alpha = Q_exp - sum(beta_exp[j] * prev_B[j] for j in Bset)
            cuts[f'cuts_{stage_idx-1}'].append((alpha, beta_exp))

        LB_k = stage_results[1]['Q']
        UB_k = total_obj_value
        LB_container.append(LB_k)
        UB_container.append(UB_k)

        if abs(LB_k - prev_LB) < tol:
            print("SDDP has converged")
            print(f"Iter {k:02d} LB = {LB_k:.6f} UB = {UB_k:.6f}")
            print("B1 End:", {j: stage_results[1]['B_end'][j] for j in Bset})
            break

        end_time = time.perf_counter()
        print(f'time taken: {end_time - start_time:.2f} seconds')
        print(f"Iter {k:02d} LB = {LB_k:.6f} UB = {UB_k:.6f}")
        start_time = time.perf_counter()
        prev_LB = LB_k

    return LB_k, cuts, LB_container, UB_container

def collect_converged_solution(data, cuts, obj, *, solver='gurobi',alpha_scd=1e-3,non_linear=False, p_control=False, integer=False,single_battery_variable=False):
    time_periods = sorted([int(x) for x in list(data['Tset'])])
    num_stages = len(time_periods)
    initial_b = data['b0']

    all_results = {}

    # Run deterministic forward pass with first scenario
    prev_B = initial_b
    total_cost = 0

    for stage_idx in range(1, num_stages + 1):

        # Solve stage with converged value functions
        Q, beta, B_end, stage_obj = solve_stage(
            stage_idx, prev_B,
            cuts.get(f'cuts_{stage_idx}', {}),
            data,
            obj,
            solver=solver,alpha_scd=alpha_scd,
            non_linear=non_linear, p_control=p_control, integer=integer,
        )

        cache_key = (int(stage_idx), bool(non_linear), bool(p_control), bool(integer),bool(single_battery_variable))
        m = MODEL_CACHE[cache_key]
        stage_vars = store_results(m)

        # Merge each variable dictionary
        for var_name, var_dict in stage_vars.items():
            if var_name not in all_results:
                all_results[var_name] = {}
            if isinstance(var_dict, dict):
                all_results[var_name].update(var_dict)

        prev_B = B_end
        total_cost += stage_obj

    return all_results

