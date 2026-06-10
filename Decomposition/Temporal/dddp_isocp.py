import os
import math
import time
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from Build_Model.store import *
from Build_Model.Constraints import get_or_build_model
from Build_Model.Objective import pyomo_solve
from Centralized.isocp import _solve_isocp,reset_isocp_cuts

# =========================================================
# SDDP solve_stage with cuts
# =========================================================
def solve_stage(m,m_solver,stage_idx, prev_stage_B, cuts_future, isocp=False):
    t = stage_idx

    for j in m.Bset:
        if m.prev_B[j].value != prev_stage_B[j]:
            m.prev_B[j].set_value(prev_stage_B[j])

    # Add new cuts (only add cuts not already in model)
    current_num_cuts = len(m.cuts)
    if len(cuts_future) > current_num_cuts:
        for i in range(current_num_cuts, len(cuts_future)):
            alpha, beta = cuts_future[i]
            cut_expr = m.theta >= alpha + sum(beta[j] * m.B[t, j] for j in m.Bset)
            m.cuts.add(cut_expr)

    reset_isocp_cuts(m)
    m_solver.solve(m)
    if isocp:
        solutions = store_results(m)
        m = _solve_isocp(prev_sol=solutions, model=m,model_solver=m_solver,gamma=0.5,inner_tol=1e-3,gap_tol=1e-3)

    # Extract results
    dual_cons = [m.battery_dynamics[t, j] for j in m.Bset]
    duals = m_solver.get_duals(cons_to_load=dual_cons)
    beta = {j: duals[m.battery_dynamics[t, j]] for j in m.Bset}
    # beta = {j: m.dual[m.battery_dynamics[t, j]] for j in m.Bset}
    Q = value(m.obj)
    S_obj = value(m.stage_cost)
    B_end = {j: value(m.B[t, j]) for j in m.Bset}
    # print(f"Stage {stage_idx} solved with Q={Q:.4f}")
    return Q, beta, B_end, S_obj


def dddp_solve(data, obj, solver='gurobi',alpha_scd=1e-3,max_iters=50, tol=1e-4, *, non_linear=False, isocp=False,p_control=False, integer=False,single_battery_variable=False):

    time_periods = sorted([int(x) for x in list(data['Tset'])])
    num_stages = len(time_periods)
    Bset = list(data['Bset'])

    # Pre-build all stage models (one-time cost)
    print("Building cached models for all stages...")
    start_time = time.perf_counter()
    for stage_idx in range(1, num_stages + 1):
        get_or_build_model( data, obj, solver,alpha_scd,stage_idx,area_name=None,non_linear=non_linear,isocp=isocp, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
    end_time = time.perf_counter()
    print(f"Built {num_stages} cached models in {end_time - start_time} seconds.")

    # Cuts storage: cuts[stage] = list of (alpha, beta) tuples
    cuts = {f'cuts_{i}': [] for i in range(1, num_stages)}

    initial_b = data['b0']
    prev_LB = 0
    LB_container = []
    UB_container = []
    algo_start_time = time.perf_counter()
    for k in range(1, max_iters + 1):
        iter_start_time = time.perf_counter()
        isocp=isocp and (k % 1 == 0)
        stage_results = {}
        total_obj_value = 0

        # FORWARD PASS
        for stage_idx in range(1, num_stages+1):
            prev_B = initial_b if stage_idx == 1 else stage_results[stage_idx-1]["B_end"]
            m, m_solver = get_or_build_model(data,obj,solver,alpha_scd,stage_idx, area_name=None, non_linear=non_linear, isocp=isocp,p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)

            Q, beta, B_end, stage_obj = solve_stage(m,m_solver,
                stage_idx, prev_B, cuts.get(f'cuts_{stage_idx}', []),isocp=isocp
            )
            stage_results[stage_idx] = {"Q": Q, "beta": beta, "B_end": B_end, "stage_obj": stage_obj}
            total_obj_value += stage_obj

        # BACKWARD PASS - compute expected cuts
        for stage_idx in range(num_stages, 1, -1):
            m, m_solver = get_or_build_model(data,obj,solver,alpha_scd,stage_idx, area_name=None, non_linear=non_linear, isocp=isocp,p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
            beta_exp = {j: 0.0 for j in Bset}
            Q_exp = 0.0
            prev_B = stage_results[stage_idx-1]["B_end"]
            Q_s, beta_s, _, _ = solve_stage(m,m_solver,
                stage_idx,
                prev_B,
                cuts.get(f'cuts_{stage_idx}', []), isocp=False
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

        if abs((UB_k - LB_k))/LB_k < tol or abs(LB_k - prev_LB) < tol:
            algo_end_time = time.perf_counter()
            print(f"DDDP has converged in Iter {k:02d} with {algo_end_time - algo_start_time:.2f} seconds, LB = {LB_k:.6f} , UB = {UB_k:.6f}")
            print("B1 End:", {j: stage_results[1]['B_end'][j] for j in Bset})
            break

        iter_end_time = time.perf_counter()
        print(f"Iter {k:02d} LB = {LB_k:.6f} UB = {UB_k:.6f},time taken: {iter_end_time - iter_start_time:.2f} seconds")
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

