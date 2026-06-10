"""
OTD-Schwarz: Overlapping Temporal Decomposition (Na et al., 2020)
Implements Algorithm 1 (Overlapping Schwarz Decomposition Procedure) exactly.

Boundary data per window i at iteration tau:
    d^tau_i = (x^tau_{m1},  x^tau_{m2},  u^tau_{m2},  lambda^tau_{m2+1})

Paper notation mapping to your code:
    m1 = ws  (left  extended boundary)
    m2 = we  (right extended boundary)
    n_i      = cs  (left  exclusive knot)
    n_{i+1}  = ce  (right exclusive knot)

The Schwarz terminal cost ~g_{m2} (Eq. 2.3) is built into build_pyomo_model
via model.B_bar_term, model.u_bar_c/u_bar_d, model.lambda_bar_next, model.rho_otd.
"""

from __future__ import annotations
import os
import time
from typing import Dict

from pyomo.environ import value
from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results


# ---------------------------------------------------------------------------
# Window layout
# ---------------------------------------------------------------------------
def _build_windows(T: int, P: int, overlap: int) -> Dict[int, Dict]:
    """
    Partition [1..T] into P exclusive intervals, each extended by `overlap`
    timesteps on both sides to form overlapping windows.
    """
    base, rem = T // P, T % P
    windows, cursor = {}, 1
    for i in range(1, P + 1):
        cs = cursor
        ce = cs + base + (1 if i <= rem else 0) - 1
        ws = max(1, cs - overlap)
        we = min(T, ce + overlap)
        windows[i] = {
            'idx': i,
            'ws': ws, 'we': we,
            'cs': cs, 'ce': ce,
            'n':  we - ws + 1,
        }
        cursor = ce + 1
    return windows


# ---------------------------------------------------------------------------
# Push Schwarz boundary data d^tau_i into the cached Pyomo model
# ---------------------------------------------------------------------------
def _update_schwarz_params(
    model,
    left_soc: Dict,       # x^tau_{m1}    -> model.prev_B        (hard BC, Eq 2.2c)
    right_soc: Dict,      # x^tau_{m2}    -> model.B_bar_term     (Eq 2.3)
    right_ctrl_c: Dict,   # u^tau_c_{m2}  -> model.u_bar_c        (Eq 2.3)
    right_ctrl_d: Dict,   # u^tau_d_{m2}  -> model.u_bar_d        (Eq 2.3)
    right_lambda: Dict,   # lambda^tau_{m2+1} -> model.lambda_bar_next (Eq 2.3)
) -> None:
    """
    Algorithm 1, line 4:
        d^tau_i = (x^tau_{m1}, x^tau_{m2}, u^tau_{m2}, lambda^tau_{m2+1})
    """
    # Left boundary — Eq. (2.2c): x_{m1} = d_{i,1}
    if hasattr(model, 'prev_B'):
        for j, v in left_soc.items():
            model.prev_B[j].set_value(float(v))

    # Right boundary data for Eq. (2.3) terminal cost (non-last windows only)
    if hasattr(model, 'B_bar_term'):
        for j, v in right_soc.items():
            model.B_bar_term[j].set_value(float(v))
    if hasattr(model, 'u_bar_c'):
        for j, v in right_ctrl_c.items():
            model.u_bar_c[j].set_value(float(v))
    if hasattr(model, 'u_bar_d'):
        for j, v in right_ctrl_d.items():
            model.u_bar_d[j].set_value(float(v))
    if hasattr(model, 'lambda_bar_next'):
        for j, v in right_lambda.items():
            model.lambda_bar_next[j].set_value(float(v))


# ---------------------------------------------------------------------------
# Extract boundary data from a solved window at time t
# ---------------------------------------------------------------------------
def _extract_boundary_data(model, t: int, Bset) -> Dict[str, Dict]:
    """
    Read x_{t}, u_{t}, lambda_{t+1} from a solved window.

    x_{t}        = B[t, j]
    u^c_{t}      = P_c[t, j]
    u^d_{t}      = P_d[t, j]  (or P_b for single-variable form)
    lambda_{t+1} = dual of battery_dynamics[t+1, j] if t+1 in Tset,
                   else dual of battery_dynamics[t, j]
    """
    soc = {}; ctrl_c = {}; ctrl_d = {}; ctrl_b = {}; lam = {}

    for j in Bset:
        soc[j] = float(value(model.B[t, j]))

        if hasattr(model, 'P_c'):
            ctrl_c[j] = float(value(model.P_c[t, j]))
        if hasattr(model, 'P_d'):
            ctrl_d[j] = float(value(model.P_d[t, j]))
        if hasattr(model, 'P_b'):
            ctrl_b[j] = float(value(model.P_b[t, j]))

        # lambda_{t+1}: dual of the constraint that produces B[t+1]
        t_lam = (t + 1) if (t + 1) in list(model.Tset) else t
        try:
            c = model.battery_dynamics[t_lam, j]
            lam[j] = float(value(model.dual[c])) if c in model.dual else 0.0
        except Exception:
            lam[j] = 0.0

    return {'soc': soc, 'ctrl_c': ctrl_c, 'ctrl_d': ctrl_d,
            'ctrl_b': ctrl_b, 'lambda': lam}


# ---------------------------------------------------------------------------
# Compose full-horizon solution from exclusive cores — Algorithm 1, line 7
# ---------------------------------------------------------------------------
def _compose_solution(all_results: Dict[int, Dict],
                      windows: Dict[int, Dict]) -> Dict:
    """
    C({~z*_i}): Definition 2.1 of the paper.
    Keep only timesteps in [cs, ce] (the exclusive core) from each window.
    """
    out: Dict = {}
    for i, w in windows.items():
        cs, ce = w['cs'], w['ce']
        for var, vdict in all_results.get(i, {}).items():
            if var == 'objective_value':
                continue
            if not isinstance(vdict, dict):
                if i == 1 and var not in out:
                    out[var] = vdict
                continue
            out.setdefault(var, {})
            for key, val in vdict.items():
                if isinstance(key, tuple) and len(key) >= 1:
                    t = key[0]
                    if cs <= t <= ce:
                        out[var][key] = val
    return out


# ---------------------------------------------------------------------------
# Convergence check at exclusive knots n_i  (paper Theorem 2.1 / Eq. 2.4)
# ---------------------------------------------------------------------------
def _check_convergence(
    prev_knot_soc: Dict[int, Dict],
    curr_knot_soc: Dict[int, Dict],
    partitions: int,
) -> float:
    """
    max_{i=1..P-1, j} |B^tau_{ce_i, j} - B^{tau-1}_{ce_i, j}|

    We measure at the exclusive right knots ce_i of windows 1..P-1,
    which are the same as the exclusive left knots cs_{i+1} of windows 2..P.
    """
    if partitions <= 1:
        return 0.0
    return max(
        abs(curr_knot_soc[i][j] - prev_knot_soc[i][j])
        for i in prev_knot_soc
        for j in prev_knot_soc[i]
    )


# ---------------------------------------------------------------------------
# Single-window solve worker
# ---------------------------------------------------------------------------
def process_window(
    w_data: Dict, window_idx: int,
    left_soc: Dict,
    right_soc: Dict, right_ctrl_c: Dict, right_ctrl_d: Dict, right_lambda: Dict,
    obj, solver: str, alpha_scd: float,
    non_linear: bool, isocp: bool, p_control: bool,
    integer: bool, single_battery_variable: bool,
):
    """
    Retrieve (or build on first call) the Pyomo model for window `window_idx`,
    push Schwarz boundary data, solve, return results and boundary extractions.

    area_name=window_idx gives each window its own MODEL_CACHE/SOLVER_CACHE slot.
    """
    model, s = get_or_build_model(
        w_data, obj, solver=solver, alpha_scd=alpha_scd,
        stage_idx=(w_data['ws'], w_data['we']),
        area_name=window_idx,                   # per-window cache key
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
    )

    _update_schwarz_params(
        model,
        left_soc=left_soc,
        right_soc=right_soc,
        right_ctrl_c=right_ctrl_c,
        right_ctrl_d=right_ctrl_d,
        right_lambda=right_lambda,
    )

    s.solve(model)
    results = store_results(model)

    Bset = list(w_data['Bset'])
    bdata_at_we = _extract_boundary_data(model, w_data['we'], Bset)
    bdata_at_ce = _extract_boundary_data(model, w_data['ce'], Bset)

    return window_idx, results, bdata_at_we, bdata_at_ce


# ---------------------------------------------------------------------------
# True objective on stitched core solution
# ---------------------------------------------------------------------------
def eval_actual_obj(
    stitched_vals: Dict, window_data_map: Dict,
    alpha_scd: float, cost,
) -> float:
    data0 = window_data_map[1]
    Bset  = list(data0['Bset'])
    eta_c = data0.get('eta_c', {})
    eta_d = data0.get('eta_d', {})
    obj_val = 0.0
    if 'P_subs' not in stitched_vals or not stitched_vals['P_subs']:
        return obj_val
    T_used = sorted({k[0] for k in stitched_vals['P_subs']})
    for t in T_used:
        psubs_t = sum(stitched_vals['P_subs'].get((t, ph), 0.0)
                      for ph in ['a', 'b', 'c'])
        obj_val += psubs_t * cost[t - 1]
    if 'P_c' in stitched_vals and 'P_d' in stitched_vals:
        for t in T_used:
            for j in Bset:
                pc = stitched_vals['P_c'].get((t, j), 0.0)
                pd = stitched_vals['P_d'].get((t, j), 0.0)
                ec = eta_c[j]
                ed = eta_d[j] if eta_d[j] != 0 else 1.0
                obj_val += alpha_scd * ((1 - ec) * pc + (1 / ed - 1) * pd)
    return obj_val


# ---------------------------------------------------------------------------
# Main Schwarz outer loop  — Algorithm 1 of Na et al. (2020)
# ---------------------------------------------------------------------------
def solve_OTD(
    window_data_map: Dict,
    windows: Dict,
    b_global_init: Dict,
    obj,
    solver: str,
    alpha_scd: float,
    non_linear: bool,
    isocp: bool,
    p_control: bool,
    integer: bool,
    single_battery_variable: bool,
    max_iters: int = 15,
    tol: float = 1e-3,
):
    """
    Algorithm 1 — Overlapping Schwarz Decomposition Procedure.

    Global iterate z^tau is stored as flat dicts keyed by (t, j):
        B_global    — SOC at every t in the union of all extended windows
        Pc_global   — P_c (charging power)
        Pd_global   — P_d (discharging power)
        lam_global  — dual of battery_dynamics, used as lambda_bar_next

    Each Schwarz iteration:
      Line 4  : d^tau_i = (x^tau_{m1}, x^tau_{m2}, u^tau_{m2}, lambda^tau_{m2+1})
      Line 5  : Solve P_i(d^tau_i) to optimality
      Line 7  : z^{tau+1} = C({~z*_i(d^tau_i)})
      Convergence: max ||B^tau_{n_i} - B^{tau-1}_{n_i}|| at knots n_i = ce_i
    """
    partitions   = len(windows)
    Bset0        = list(window_data_map[1]['Bset'])
    tmin_horizon = min(windows[i]['ws'] for i in windows)

    all_t = sorted({t for w in windows.values()
                    for t in range(w['ws'], w['we'] + 1)})

    # z^0: SOC = b0 everywhere, controls = 0, duals = 0
    B_global   = {(t, j): b_global_init[j] for t in all_t for j in Bset0}
    Pc_global  = {(t, j): 0.0              for t in all_t for j in Bset0}
    Pd_global  = {(t, j): 0.0              for t in all_t for j in Bset0}
    lam_global = {(t, j): 0.0              for t in all_t for j in Bset0}

    all_results: Dict[int, Dict] = {}
    converged = False
    max_delta = float('inf')
    t0_wall   = time.perf_counter()

    for k in range(1, max_iters + 1):
        tk = time.perf_counter()

        # Save SOC at exclusive right knots BEFORE this iteration
        prev_knot_soc = {
            i: {j: B_global[(windows[i]['ce'], j)] for j in Bset0}
            for i in range(1, partitions)   # ce_1, ce_2, ..., ce_{P-1}
        }

        # ------------------------------------------------------------------
        # Algorithm 1 lines 3-6
        # ------------------------------------------------------------------
        for i, w in windows.items():
            ws, we = w['ws'], w['we']

            # d_{i,1} = x^tau_{m1}
            # First window: dynamics already use b0 when tmin_local==tmin_horizon;
            # we push b_global_init to prev_B for consistency.
            if ws == tmin_horizon:
                left_soc = dict(b_global_init)
            else:
                left_soc = {j: B_global[(ws, j)] for j in Bset0}

            # d_{i,2:4} = (x^tau_{m2}, u^tau_{m2}, lambda^tau_{m2+1})
            right_soc    = {j: B_global  [(we, j)] for j in Bset0}
            right_ctrl_c = {j: Pc_global [(we, j)] for j in Bset0}
            right_ctrl_d = {j: Pd_global [(we, j)] for j in Bset0}
            right_lambda = {j: lam_global[(we, j)] for j in Bset0}

            _, res, bdata_we, _ = process_window(
                w_data=window_data_map[i],
                window_idx=i,
                left_soc=left_soc,
                right_soc=right_soc,
                right_ctrl_c=right_ctrl_c,
                right_ctrl_d=right_ctrl_d,
                right_lambda=right_lambda,
                obj=obj, solver=solver, alpha_scd=alpha_scd,
                non_linear=non_linear, isocp=isocp,
                p_control=p_control, integer=integer,
                single_battery_variable=single_battery_variable,
            )
            all_results[i] = res

            # Update global iterate over this window's full extended range
            # so that neighbouring windows see the latest x^tau at their
            # m1 = ws and m2 = we in the NEXT iteration.
            for (t, jj), v in res.get('B',   {}).items():
                if jj in Bset0:
                    B_global[(t, jj)] = v
            for (t, jj), v in res.get('P_c', {}).items():
                if jj in Bset0:
                    Pc_global[(t, jj)] = v
            for (t, jj), v in res.get('P_d', {}).items():
                if jj in Bset0:
                    Pd_global[(t, jj)] = v

            # lambda at m2 extracted from this window's dual of battery_dynamics
            for j in Bset0:
                lam_global[(we, j)] = bdata_we['lambda'].get(j, 0.0)

        # ------------------------------------------------------------------
        # Algorithm 1 line 7: z^{tau+1} = C({~z*_i})
        # ------------------------------------------------------------------
        composed = _compose_solution(all_results, windows)

        # ------------------------------------------------------------------
        # Convergence check at exclusive knots
        # ------------------------------------------------------------------
        curr_knot_soc = {
            i: {j: B_global[(windows[i]['ce'], j)] for j in Bset0}
            for i in range(1, partitions)
        }
        max_delta = _check_convergence(prev_knot_soc, curr_knot_soc, partitions)

        print(f"  iter {k:02d} | ΔB_knot = {max_delta:.6f} | "
              f"t = {time.perf_counter() - tk:.2f}s")

        if max_delta < tol:
            print(f"  Converged in {k} iters | "
                  f"total = {time.perf_counter() - t0_wall:.1f}s")
            converged = True
            break

    if not converged:
        print(f"  WARNING: not converged after {max_iters} iters. "
              f"Final ΔB_knot = {max_delta:.6f}")

    return composed, converged


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles
    from Plot.Plotting import plot_battery_soc

    system_name = 'IEEE_123_other'
    wd       = os.getcwd()
    filepath = os.path.join(wd, '..', '..', 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, '..', '..', 'rawData', system_name,
                            'dss_scripts', 'Master.dss')

    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price          = 0.15 * loadshape_data['M'] + 0.15

    obj_fn                  = cost_minimize_with_scd
    multi                   = True
    non_linear              = False
    isocp                   = False
    p_control               = False
    integer                 = False
    single_battery_variable = False
    solver                  = 'ipopt' if non_linear else 'gurobi'
    alpha_scd               = 1e-3
    n_total                 = 24
    partitions              = 4
    overlap                 = 2
    v_min_val, v_max_val    = 0.9, 1.1
    max_iters               = 15
    tol                     = 1e-3

    windows = _build_windows(n_total, partitions, overlap)
    print(f"\nOTD-Schwarz | T=1..{n_total} | P={partitions} | overlap={overlap}")
    for i in range(1, partitions + 1):
        w = windows[i]
        print(f"  Win {w['idx']}: extended=[{w['ws']},{w['we']}]  "
              f"core=[{w['cs']},{w['ce']}]  "
              f"left_buf={list(range(w['ws'], w['cs'])) or 'none'}  "
              f"right_buf={list(range(w['ce'] + 1, w['we'] + 1)) or 'none'}")

    print("\nParsing window data...")
    window_data_map = {}
    for i in range(1, partitions + 1):
        w = windows[i]
        d = parse_all_data_phase_aware(
            bus_data, branch_data, gen_data, bat_data,
            loadshape=loadshape_data, pvshape=pvshape_data,
            price=price, start_step=w['ws'], n_steps=w['n'])
        d['v_min'] = {k: v_min_val for k in d['v_min']}
        d['v_max'] = {k: v_max_val for k in d['v_max']}
        d['ws'] = w['ws'];  d['we'] = w['we']
        d['cs'] = w['cs'];  d['ce'] = w['ce']
        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi)
            d['I_ang'] = angles['I_ang']
        window_data_map[w['idx']] = d

    b_global_init = dict(window_data_map[1]['b0'])

    t0 = time.time()
    vals, converged = solve_OTD(
        window_data_map, windows, b_global_init,
        obj_fn, solver, alpha_scd,
        non_linear, isocp, p_control, integer, single_battery_variable,
        max_iters=max_iters, tol=tol,
    )
    obj_val = eval_actual_obj(vals, window_data_map, alpha_scd, price)
    print(f"\nDone in {time.time() - t0:.2f}s | Converged: {converged} | "
          f"Obj: {obj_val:.6f}")
    plot_battery_soc(OTDVals=vals)