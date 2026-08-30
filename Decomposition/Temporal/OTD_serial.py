"""
OTD-Schwarz: Overlapping Temporal Decomposition (Na et al., 2020)
Bidirectional SOC boundary exchange at core partition edges.
Parallel via mp.Pool.starmap — mirrors solve_EnAPP commented-out block exactly.
"""
from Plot.Plotting import *
import os
import time
import multiprocessing as mp
from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results


# ── Window layout ─────────────────────────────────────────────────────────────
def _build_windows(T, P, overlap):
    base, rem = T // P, T % P
    windows, cursor = {}, 1
    for i in range(1,P+1):
        cs = cursor
        ce = cs + base + (1 if i <= rem else 0) - 1
        ws, we = max(1, cs - overlap), min(T, ce + overlap)
        windows[i] = {
            'idx': i,
            'ws':  ws,  'we':  we,
            'cs':  cs,  'ce':  ce,
            'n':   we - ws + 1,
        }
        # Left/right boundary times (interfaces)
        windows[i]['soc_passing_boundary'] = ce-overlap
        windows[i]['dual_passing_boundary'] = we-overlap+1
        cursor = ce + 1
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

    if w_data.get('soc_receiving_initial'):
        for j in model.Bset:
            model.prev_B[j] = w_data['soc_receiving_initial'][j]
    if w_data.get('dual_receiving_terminal'):
        for j in model.Bset:
            model.term_dual[j] = w_data['dual_receiving_terminal'][j]

    s.solve(model)
    # Extract duals
    t = w_data['dual_passing_boundary']
    dual_cons = [model.battery_dynamics[t, j] for j in model.Bset]
    duals = s.get_duals(cons_to_load=dual_cons)
    beta = {j: duals[model.battery_dynamics[t, j]] for j in model.Bset}
    return window_idx, store_results(model),beta


# ── Extract core boundary SOCs ────────────────────────────────────────────────
def _compute_boundary_socs_duals(windows, all_results,duals, window_data_map):
    D_win_passing, B_win_passing = {}, {}
    for i, w  in windows.items():
        B_vals = all_results[i].get('B', {})
        D_vals = dict(duals[i])
        Bset   = list(window_data_map[i]['Bset'])

        tgt_soc_passing         = w['soc_passing_boundary']
        B_win_passing[i] = {j: B_vals[tgt_soc_passing, j] for j in Bset}
        D_win_passing[i] = dict(duals[i])

    return B_win_passing, D_win_passing


# ── Push boundary SOCs into window data ──────────────────────────────────────
def _update_window_boundaries(windows, window_data_map,B_win_passing,D_win_passing,
                               partitions):
    for i, _ in windows.items():
        window_data_map[i]['soc_sending'] = (dict(B_win_passing[i]))
        window_data_map[i]['dual_sending'] = (dict(D_win_passing[i]))
        window_data_map[i]['dual_receiving_terminal'] = (dict(D_win_passing[i+1])) if i < partitions else {}
        window_data_map[i]['soc_receiving_initial'] = (dict(b_global_init) if i == 1 else dict(B_win_passing[i - 1]))
    return window_data_map

def _stitch_results(all_results, windows):
    out = {}

    # Stitch only core timesteps from each window
    for i, w in windows.items():
        cs = w['cs']
        ce = w['ce']

        for var, vdict in all_results.get(i, {}).items():
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
    eta_c = data0.get('eta_c', {})
    eta_d = data0.get('eta_d', {})

    obj = 0.0

    if 'P_subs' in stitched_vals and stitched_vals['P_subs']:
        T_used = sorted({k[0] for k in stitched_vals['P_subs'].keys()})

        for t in T_used:
            psubs_t = sum(stitched_vals['P_subs'][t, ph] for ph in ['a','b','c'])
            obj += psubs_t * cost[t-1]

        if 'P_c' in stitched_vals and 'P_d' in stitched_vals:
            for t in T_used:
                for j in Bset:
                    pc = stitched_vals['P_c'].get((t, j), 0.0)
                    pd = stitched_vals['P_d'].get((t, j), 0.0)
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
    Bset0 = list(window_data_map[1]['Bset'])
    B_win_passing = {i: dict(b_global_init) for i in range(1,partitions+1)}
    D_win_passing = {i: {j: 0.0 for j in Bset0} for i in range(1, partitions + 1)}
    all_results  = {}
    converged    = False
    max_delta    = float('inf')
    t0           = time.perf_counter()


    for k in range(1, max_iters + 1):
        tk = time.perf_counter()

        results = [process_window(window_data_map[i], i,
                 obj, solver, alpha_scd,
                 non_linear, isocp, p_control, integer, single_battery_variable)
                for i, _ in windows.items()
        ]
        all_results = {idx: res for idx, res, beta in results}
        duals = {idx:beta for idx,res,beta in results}

        new_B_win_passing,new_D_win_passing= _compute_boundary_socs_duals(
            windows, all_results, duals,window_data_map)

        max_delta = max(
            abs(new_B_win_passing[i][j] - B_win_passing[i][j])
            for i in range(1, partitions)
            for j in new_B_win_passing[i]
        ) if partitions > 1 else 0.0

        B_win_passing = new_B_win_passing
        D_win_passing = new_D_win_passing

        window_data_map = _update_window_boundaries(
            windows, window_data_map,B_win_passing,D_win_passing, partitions)

        print(f"  iter {k:02d} | ΔB = {max_delta:.6f} | "
              f"t = {time.perf_counter() - tk:.1f}s")

        # if max_delta < tol:
        #     print(f"  Converged in {k} iters | "
        #           f"total = {time.perf_counter() - t0:.1f}s")
        #     converged = True
        #     break

    if not converged:
        print(f"  WARNING: not converged after {max_iters} iters. "
              f"Final ΔB = {max_delta:.6f}")

    return _stitch_results(all_results, windows), converged


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
    isocp                   = True
    p_control               = False
    integer                 = False
    single_battery_variable = False
    solver                  = 'ipopt' if non_linear else 'highs'
    alpha_scd               = 1e-3
    n_total                 = 24
    partitions              = 6
    overlap                 = 2
    v_min_val, v_max_val    = 0.9, 1.1
    max_iters               = 15
    tol                     = 1e-3

    windows = _build_windows(n_total, partitions, overlap)
    print(f"\nOTD-Schwarz | T=1..{n_total} | P={partitions} | overlap={overlap}")
    for i in range(1, partitions + 1):
        w = windows[i]
        print(f"  Win {w['idx']}: window=[{w['ws']},{w['we']}]  "
              f"core=[{w['cs']},{w['ce']}]  "
              f"left_buf={list(range(w['ws'], w['cs'])) or 'none'}  "
              f"right_buf={list(range(w['ce']+1, w['we']+1)) or 'none'}")

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
        d['cs']    = w['cs']
        d['ce']    = w['ce']
        d['soc_passing_boundary'] = w['soc_passing_boundary']
        d['dual_passing_boundary'] = w['dual_passing_boundary']
        d['soc_receiving_initial'] = {}
        d['dual_receiving_terminal'] = {}
        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi)
            d['I_ang'] = angles['I_ang']
        window_data_map[w['idx']] = d

    b_global_init = dict(window_data_map[1]['b0'])

    t0 = time.time()
    vals, converged = solve_OTD(
        window_data_map, windows, b_global_init,
        obj, solver, alpha_scd,
        non_linear, isocp, p_control, integer, single_battery_variable,
        max_iters=max_iters, tol=tol,
    )
    obj = eval_actual_obj(vals,window_data_map,alpha_scd,price)
    print(f"\nDone in {time.time()-t0:.2f}s | Converged: {converged} | "
          f"Obj: {obj}")

    plot_battery_soc(OTDVals = vals)
