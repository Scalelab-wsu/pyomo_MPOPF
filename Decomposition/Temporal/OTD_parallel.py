"""
OTD-Schwarz: Overlapping Temporal Decomposition (Na et al., 2020)
Bidirectional SOC boundary exchange at core partition edges.
Parallel via mp.Pool.starmap — mirrors solve_EnAPP commented-out block exactly.
"""

import os
import time
import multiprocessing as mp
from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results
from Plot.Plotting import *

# ── Window layout ─────────────────────────────────────────────────────────────
def build_windows(T, partitions, overlap):
    base = T // partitions
    windows = {}
    for i in range(partitions):
        cs = i * base + 1
        ce   = (i + 1) * base
        ws      = max(cs - overlap, 1)
        we      = min(ce  + overlap, T)
        windows[i+1] = {"cs":cs,"ce":ce,"ws": ws, "we": we,"n":we-ws+1}
    return windows


# ── Worker — mirrors process_area exactly ─────────────────────────────────────
def process_window(w_data, window_idx, obj, solver, alpha_scd,
                   non_linear, isocp, p_control, integer, single_battery_variable):
    """
    area_name=window_idx gives each window its own MODEL_CACHE slot.
    First call: builds model + solver, caches in worker process memory.
    Subsequent calls: returns cached model, only updates mutable params.
    """
    model, s = get_or_build_model(
        w_data, obj, solver=solver, alpha_scd=alpha_scd,
        stage_idx=(w_data['ws'], w_data['we']),
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
    )

    # Update mutable boundary params
    for j in model.Bset:
        model.prev_B[j] = w_data['prev_B'][j]
        model.term_B[j] = w_data['term_B'][j]
        model.term_Pc[j] = w_data['term_Pc'][j]
        model.term_Pd[j] = w_data['term_Pd'][j]
        model.term_dual[j] = w_data['term_dual'][j]

    s.solve(model)
    results = store_results(model)
    if hasattr(model, 'dual'):
        results['duals'] = {
            (t, j): model.dual[model.battery_dynamics[t, j]]
            for t in model.Tset
            for j in model.Bset
        }
    else:
        cons = {(t, j): model.battery_dynamics[t, j] for t in model.Tset for j in model.Bset}
        duals = s.get_duals(cons_to_load=list(cons.values()))
        results['duals'] = {k: duals[v] for k, v in cons.items()}
    return window_idx, results

# ── Extract core boundary SOCs ────────────────────────────────────────────────
def _compute_boundary_vals(windows, all_results, window_data_map):
    B_start,B_end,Pc_end,Pd_end,dual_end = {}, {}, {}, {}, {}
    for i in windows:
        B_vals = all_results[i]['B']
        Pc_vals = all_results[i]['P_c']
        Pd_vals = all_results[i]['P_d']
        duals = all_results[i]['duals']
        Bset   = list(window_data_map[i]['Bset'])

        if i - 1 in windows:
            tgt_term     = windows[i-1]['we']
            B_end[i]     = {j: B_vals[tgt_term, j] for j in Bset}
            Pc_end[i] = {j:Pc_vals[tgt_term,j] for j in Bset}
            Pd_end[i] = {j: Pd_vals[tgt_term, j] for j in Bset}
            dual_end[i] = {j: duals[tgt_term + 1, j]    for j in Bset}

        if i + 1 in windows:
            tgt_init     = windows[i+1]['ws'] - 1
            B_start[i]   = {j: B_vals[tgt_init, j] for j in Bset}

    return  B_start,B_end,Pc_end,Pd_end,dual_end

# ── Push boundary SOCs into window data ──────────────────────────────────────
def _update_window_boundaries(windows, window_data_map,
                               B_start,B_end, Pc_end,Pd_end,dual_end,
                               b_global_init, partitions):
    for i, _ in windows.items():
        window_data_map[i]['prev_B'] = (dict(b_global_init) if i == 1 else dict(B_start[i - 1]))
        window_data_map[i]['b_end'] = (dict(B_end[i + 1]) if i < partitions else {})
        window_data_map[i]['Pc_end'] = (dict(Pc_end[i + 1]) if i < partitions else {})
        window_data_map[i]['Pd_end'] = (dict(Pd_end[i + 1]) if i < partitions else {})
        window_data_map[i]['dual_end'] = (dict(dual_end[i + 1]) if i < partitions else {})
    return window_data_map


def _stitch_results(all_results, windows):
    out = {}

    # Stitch only core timesteps from each window
    for i, w in windows.items():
        cs = w['cs']
        ce = w['ce']

        for var, vdict in all_results[i].items():
            if var == 'objective_value':
                continue

            if not isinstance(vdict, dict):
                if i == 1 and var not in out:
                    out[var] = vdict
                continue

            out.setdefault(var, {})

            for key, val in vdict.items():
                if isinstance(key, tuple):
                    t = key[0]
                    if cs <= t <= ce:
                        out[var][key] = val
    return out

def eval_actual_obj(stitched_vals,window_data_map,alpha_scd,cost):
    data0 = window_data_map[1]
    Bset = list(data0['Bset'])
    eta_c = data0['eta_c']
    eta_d = data0['eta_d']

    obj = 0.0

    if 'P_subs' in stitched_vals and stitched_vals['P_subs']:
        T_used = sorted({k[0] for k in stitched_vals['P_subs'].keys()})

        for t in T_used:
            psubs_t = sum(stitched_vals['P_subs'][t, ph] for ph in ['a','b','c'])
            obj += psubs_t * cost[t-1]

        if 'P_c' in stitched_vals and 'P_d' in stitched_vals:
            for t in T_used:
                for j in Bset:
                    pc = stitched_vals['P_c'][t, j]
                    pd = stitched_vals['P_d'][t, j]
                    ec = eta_c[j]
                    ed = eta_d[j]

                    obj += alpha_scd * (
                        (1 - ec) * pc +
                        (((1 / ed) - 1) if ed != 0 else 1.0) * pd
                    )
    return obj

# ── Main Schwarz loop — mirrors solve_EnAPP commented-out mp.Pool block ───────
def solve_OTD(window_data_map, windows, b_global_init,
              obj, solver, alpha_scd,
              non_linear, isocp, p_control, integer, single_battery_variable,
              max_iters=15, tol=1e-3):

    partitions = len(windows)
    n_workers  = min(partitions, os.cpu_count() or partitions)

    B_end   = {i: dict(b_global_init) for i in range(1,partitions+1)}
    B_start = {i: dict(b_global_init) for i in range(1,partitions+1)}
    all_results  = {}
    converged    = False
    max_delta    = float('inf')
    t0           = time.perf_counter()

    with mp.Pool(processes=n_workers) as pool:
        for k in range(1, max_iters + 1):
            tk = time.perf_counter()

            results = pool.starmap(
                process_window,
                [
                    (window_data_map[i], i,
                     obj, solver, alpha_scd,
                     non_linear, isocp, p_control, integer, single_battery_variable)
                    for i, _ in windows.items()
                ]
            )
            all_results = {idx: res for idx, res in results}

            new_B_start,new_B_end,new_Pc_end,new_Pd_end,new_dual_end = _compute_boundary_vals(
                windows, all_results, window_data_map)

            if partitions > 1:
                delta_end = max(
                    abs(new_B_end[i][j] - B_end[i][j])
                    for i in range(2,partitions+1)
                    for j in new_B_end[i])
                delta_start = max(
                    abs(new_B_start[i][j] - B_start[i][j])
                    for i in range(1, partitions)
                    for j in new_B_start[i])
                max_delta = max(delta_end, delta_start)
            else:
                max_delta = 0.0

            B_end   = new_B_end
            B_start = new_B_start
            Pc_end = new_Pc_end
            Pd_end = new_Pd_end
            dual_end = new_dual_end

            window_data_map = _update_window_boundaries(
                windows, window_data_map, B_start, B_end, Pc_end, Pd_end,dual_end,
                b_global_init, partitions)

            print(f"  iter {k:02d} | ΔB = {max_delta:.6f} | "
                  f"t = {time.perf_counter() - tk:.1f}s")

            if k > 1 and max_delta < tol:
                print(f"  Converged in {k} iters | "
                      f"total = {time.perf_counter() - t0:.1f}s")
                converged = True
                break

    if not converged:
        print(f"  WARNING: not converged after {max_iters} iters. "
              f"Final ΔB = {max_delta:.6f}")

    return _stitch_results(all_results, windows), B_end, converged


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles

    system_name = 'IEEE_123_other'
    wd          = os.getcwd()
    filepath    = os.path.join(wd, '..', '..', 'rawData', system_name, 'csvs')
    dss_path    = os.path.join(wd, '..', '..', 'rawData', system_name,
                               'dss_scripts', 'Master.dss')

    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price          = 0.15 * loadshape_data['M'] + 0.15

    obj                     = cost_minimize_with_scd
    multi                   = True
    non_linear              = False
    isocp                   = False
    p_control               = False
    integer                 = False
    single_battery_variable = False
    solver                  = 'ipopt' if non_linear else 'gurobi'
    alpha_scd               = 1e-2
    n_total                 = 24
    partitions              = 4
    overlap                 = 2
    v_min_val, v_max_val    = 0.9, 1.1
    max_iters               = 15
    tol                     = 1e-3

    windows = build_windows(n_total, partitions, overlap)
    print(f"\nOTD-Schwarz | T=1..{n_total} | P={partitions} | overlap={overlap}")
    for i in range(1, partitions + 1):
        w = windows[i]
        print(f"  Win {w}: window=[{w['ws']},{w['we']}]  ")

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
        d['ws']    = w['ws']
        d['we']    = w['we']
        d['prev_B'] = dict(d['b0'])
        d['term_B'] = dict(d['b0'])
        d['term_Pc'] = {j:0 for j in d['Bset']}
        d['term_Pd'] = {j:0 for j in d['Bset']}
        d['term_dual'] = {j:0 for j in d['Bset']}

        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi)
            d['I_ang'] = angles['I_ang']
        window_data_map[i] = d

    b_global_init = dict(window_data_map[1]['b0'])

    t0 = time.time()
    vals, B_final, converged = solve_OTD(
        window_data_map, windows, b_global_init,
        obj, solver, alpha_scd,
        non_linear, isocp, p_control, integer, single_battery_variable,
        max_iters=max_iters, tol=tol,
    )
    obj = eval_actual_obj(vals,window_data_map,alpha_scd,price)
    print(f"\nDone in {time.time()-t0:.2f}s | Converged: {converged} | "
          f"Obj: {obj}")
    plot_battery_soc(OTDVals=vals)