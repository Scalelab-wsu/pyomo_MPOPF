"""
OTD-Schwarz: Overlapping Temporal Decomposition (Na et al., 2020)
Bidirectional SOC boundary exchange at core partition edges.
Parallel via mp.Pool.starmap — mirrors solve_EnAPP commented-out block exactly.
"""
 
import os
import sys
import time
import pickle
import tempfile
import multiprocessing as mp
 
# Add project root to path so Build_Model, Plot, etc. are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# _grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
# if os.path.exists(_grb_ca):
#     os.environ['GRB_CAFILE'] = _grb_ca
# Ensure idaes-installed solvers (ipopt) are on PATH
_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')
 
# Multiprocessing context. Use 'fork' for IPOPT/HiGHS (fork-safe and fastest).
# Switch to 'forkserver' if you ever use Gurobi/Mosek — they are not fork-safe.
# Pre-serialisation of window data (done in solve_OTD) keeps the per-worker
# IPC overhead small regardless of the context chosen.
_MP_CTX = mp.get_context('forkserver')

from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results
from Centralized.isocp import _solve_isocp, reset_isocp_cuts
from Plot.Plotting import *
 
# ── Window layout ─────────────────────────────────────────────────────────────
def build_windows(T, partitions, overlap=None):
    """Build symmetrically overlapping windows (Na et al. Theorem 8).

    Each window spans [ws, we] where:
      ws = max(cs - overlap, 1)  (left extension damps left-boundary error by rho^overlap)
      we = min(ce + overlap, T)  (right extension damps right-boundary error by rho^overlap)

    With symmetric overlap the Schwarz rate is alpha = 2*Upsilon*rho^overlap < 1
    once overlap >= ceil(log(2*Upsilon)/log(1/rho)) + 1.  overlap = T//partitions
    is a safe default; smaller values work in practice.
    """
    base = T // partitions
    if overlap is None:
        overlap = base
    windows = {}
    for i in range(partitions):
        cs = i * base + 1
        ce = (i + 1) * base
        ws = max(cs - overlap, 1)  # symmetric left extension
        we = min(ce + overlap, T)
        windows[i+1] = {"cs": cs, "ce": ce, "ws": ws, "we": we, "n": we - ws + 1}
    return windows
 
 
# ── Dedicated persistent process for one OTD window ────────────────────
_IDAES_BIN = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
 
def _window_worker_process(window_idx, data_path, obj, solver, alpha_scd,
                            non_linear, isocp, p_control, integer,
                            single_battery_variable, recv_conn, send_conn):
    """One process per window. Builds its model ONCE then loops solve/send.
    Receives a file path instead of the data dict — avoids large IPC pickle
    overhead on forkserver/spawn. The OS page-cache makes the file load fast.
    Only tiny boundary dicts (prev_B, term_B) cross the pipe each iteration.
    """
    if _IDAES_BIN not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _IDAES_BIN + os.pathsep + os.environ.get('PATH', '')

    with open(data_path, 'rb') as f:
        w_data = pickle.load(f)

    model, s = get_or_build_model(
        w_data, obj, solver=solver, alpha_scd=alpha_scd,
        stage_idx=(w_data['ws'], w_data['we']),
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
    )
    Bset = list(model.Bset)
    send_conn.send(None)          # signal: model ready

    while True:
        msg = recv_conn.recv()
        if msg is None:           # shutdown
            break
        prev_B, term_B, term_dual, run_isocp = msg
        for j in Bset:
            model.prev_B[j] = prev_B[j]
            model.term_B[j] = term_B[j]
            model.term_dual[j] = term_dual[j]

        if isocp:
            reset_isocp_cuts(model)
        s.solve(model)
        if isocp and run_isocp:
            # Match the Schwarz outer tol (1e-3) rather than the default 1e-4.
            model, _ = _solve_isocp(prev_sol=store_results(model), model=model,
                                    model_solver=s,
                                    inner_tol=1e-3, gap_tol=1e-3, max_inner=5)

        if hasattr(s, 'get_duals'):
            dual_cons = [model.battery_dynamics[t, j] for t in model.Tset for j in Bset]
            duals_raw = s.get_duals(cons_to_load=dual_cons)
            dual = {(t, j): duals_raw[model.battery_dynamics[t, j]]
                    for t in model.Tset for j in Bset}
        elif hasattr(model, 'dual'):
            dual = {(t, j): model.dual[model.battery_dynamics[t, j]]
                    for t in model.Tset for j in Bset}
        else:
            raise RuntimeError(
                f"Window {window_idx}: no dual extraction method available.")

        solution = store_results(model)
        solution['dual'] = dual
        send_conn.send(solution)
 
# ── Extract core boundary SOCs ────────────────────────────────────────────────
def _compute_boundary_vals(windows, all_results, window_data_map):
    B_start, B_end, dual_end = {}, {}, {}
    for i in windows:
        B_vals = all_results[i]['B']
        dual_vals = all_results[i]['dual']
        Bset   = list(window_data_map[i]['Bset'])

        if i - 1 in windows:
            tgt_term   = windows[i-1]['we']
            B_end[i]   = {j: B_vals[tgt_term, j] for j in Bset}

            dual_end[i] = {
                j: dual_vals.get((tgt_term + 1, j), dual_vals.get((tgt_term, j), 0.0))
                for j in Bset
            }

        if i + 1 in windows:
            tgt_init   = windows[i+1]['ws'] - 1
            if tgt_init >= 1:  # guard: ws==1 means window uses b0 naturally
                B_start[i] = {j: B_vals[tgt_init, j] for j in Bset}

    return B_start, B_end, dual_end

# ── Push boundary SOCs into window data ──────────────────────────────────────
def _update_window_boundaries(windows, window_data_map,
                               B_start, B_end, dual_end,
                               b_global_init, partitions):
    for i, _ in windows.items():
        # Left BC: use b0 for window 1 or if previous window's B_start wasn't computed
        # (edge case: when ws==1, battery_dynamics uses b0 anyway via tmin_horizon branch)
        window_data_map[i]['prev_B'] = (dict(b_global_init)
                                        if i == 1 or (i - 1) not in B_start
                                        else dict(B_start[i - 1]))
        # Right BC: use next window's boundary SOC
        if i < partitions:
            window_data_map[i]['term_B'] = dict(B_end[i + 1])
            window_data_map[i]['term_dual'] = dict(dual_end[i + 1])
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

# ── Main Schwarz loop ─────────────────────────────────────────────────────────
def solve_OTD(window_data_map, windows, b_global_init,
              obj, solver, alpha_scd,
              non_linear, isocp, p_control, integer, single_battery_variable,
              max_iters=15, tol=1e-3, omega=1.0):
    """omega : under-relaxation on term_B / term_dual (NOT prev_B). Default
    1.0 — the rho_prox quadratic in cost_minimize_with_scd is sufficient
    regularization. rho_prox is hardcoded to 0.3 in Build_Model/Objective.py.
    """
    partitions = len(windows)
    all_results  = {}
    converged    = False
    max_delta    = float('inf')
    t0           = time.perf_counter()
    iter_times   = []
    delta_history = []

    # Pre-serialise each window's data to a temp file (done once in the parent).
    t_serial_start = time.perf_counter()
    _tmpdir = tempfile.mkdtemp(prefix='otd_worker_')
    data_paths = {}
    for i in windows:
        path = os.path.join(_tmpdir, f'window_{i}.pkl')
        with open(path, 'wb') as f:
            pickle.dump(window_data_map[i], f, protocol=pickle.HIGHEST_PROTOCOL)
        data_paths[i] = path
    t_serial = time.perf_counter() - t_serial_start

    # Launch one persistent process per window — all build in parallel
    send_conns, recv_conns = {}, {}
    procs = []
    t_launch_start = time.perf_counter()
    for i in windows:
        p_recv, c_send = _MP_CTX.Pipe(duplex=False)   # child → parent
        c_recv, p_send = _MP_CTX.Pipe(duplex=False)   # parent → child
        p = _MP_CTX.Process(
            target=_window_worker_process,
            args=(i, data_paths[i], obj, solver, alpha_scd,
                  non_linear, isocp, p_control, integer, single_battery_variable,
                  c_recv, c_send),
            daemon=True,
        )
        p.start()
        send_conns[i] = p_send
        recv_conns[i] = p_recv
        procs.append(p)

    # Wait until all models are built (processes signal None when ready)
    print(f"  Launching {partitions} dedicated worker processes...", flush=True)
    for i in windows:
        recv_conns[i].recv()
    t_build = time.perf_counter() - t_launch_start
    print(f"  All models built in {t_build:.2f}s | starting iterations", flush=True)

    B_end    = {i: dict(b_global_init) for i in range(1, partitions+1)}
    B_start  = {i: dict(b_global_init) for i in range(1, partitions+1)}
    _bset    = list(window_data_map[1]['Bset'])
    dual_end = {i: {j: 0.0 for j in _bset} for i in range(1, partitions+1)}

    try:
        for k in range(1, max_iters + 1):
            tk = time.perf_counter()

            for i in windows:
                send_conns[i].send((window_data_map[i]['prev_B'],
                                    window_data_map[i]['term_B'],
                                    window_data_map[i]['term_dual'],
                                    False))

            all_results = {i: recv_conns[i].recv() for i in windows}

            new_B_start, new_B_end, new_dual_end = _compute_boundary_vals(
                windows, all_results, window_data_map)

            if partitions > 1:
                delta_end = max(
                    (abs(new_B_end[i][j] - B_end[i][j])
                     for i in new_B_end if i in B_end
                     for j in new_B_end[i]),
                    default=0.0)
                delta_start = max(
                    (abs(new_B_start[i][j] - B_start[i][j])
                     for i in new_B_start if i in B_start
                     for j in new_B_start[i]),
                    default=0.0)
                max_delta = max(delta_end, delta_start)
            else:
                max_delta = 0.0

            if isocp:
                w = omega
                for i in new_B_end:
                    B_end[i] = {j: w * new_B_end[i][j] + (1 - w) * B_end[i][j]
                                for j in new_B_end[i]}
                for i in new_dual_end:
                    dual_end[i] = {j: w * new_dual_end[i][j] + (1 - w) * dual_end[i][j]
                                   for j in new_dual_end[i]}
                B_start = new_B_start
            else:
                B_end = new_B_end
                B_start = new_B_start
                dual_end = new_dual_end

            window_data_map = _update_window_boundaries(
                windows, window_data_map, B_start, B_end, dual_end,
                b_global_init, partitions)

            iter_t = time.perf_counter() - tk
            iter_times.append(iter_t)
            delta_history.append(max_delta)
            print(f"  iter {k:02d} | ΔB = {max_delta:.6f} | t = {iter_t:.2f}s")

            if max_delta < tol:
                converged = True
                print(f"  Converged | total = {time.perf_counter() - t0:.2f}s")
                break

        # Final ISOCP refinement pass once Schwarz boundaries have converged.
        # Each window solves one full convex-iteration loop at the fixed boundary.
        if isocp:
            print("  Running final ISOCP refinement...", flush=True)
            for i in windows:
                send_conns[i].send((window_data_map[i]['prev_B'],
                                    window_data_map[i]['term_B'],
                                    window_data_map[i]['term_dual'],
                                    True))
            all_results = {i: recv_conns[i].recv() for i in windows}
            print("  ISOCP refinement done.", flush=True)
    finally:
        # Shut down all worker processes cleanly
        for i in windows:
            try: send_conns[i].send(None)
            except Exception: pass
        for p in procs:
            p.join(timeout=5)
    if not converged:
        print(f"  WARNING: not converged after {max_iters} iters. "
              f"Final ΔB = {max_delta:.6f}")

    timing = {
        'total_s':       time.perf_counter() - t0,
        'serial_s':      t_serial,
        'build_s':       t_build,
        'iter_times':    iter_times,
        'delta_history': delta_history,
        'n_iters':       len(iter_times),
        'avg_iter_s':    sum(iter_times) / len(iter_times) if iter_times else 0.0,
        'converged':     converged,
    }
    return _stitch_results(all_results, windows), B_end, converged, timing
 
 
# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles
 
    # system_name = 'IEEE_123'
    system_name = 'IEEE_9500'
    wd          = os.path.join(os.path.dirname(__file__), '..', '..')
    filepath    = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path    = os.path.join(wd, 'rawData', system_name,
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
    solver                  = 'gurobi'
    alpha_scd               = 1e-2
    n_total                 = 24
    partitions              = 8
    base                    = n_total // partitions
    overlap                 = base   # symmetric overlap each side; rate = 2*Υ*ρ^overlap
    v_min_val, v_max_val    = 0.9, 1.2
    max_iters               = 100
    tol                     = 1e-3
    omega                   = 1.0

    windows = build_windows(n_total, partitions, overlap)
    print(f"\nOTD-Schwarz | T=1..{n_total} | P={partitions} | base={base}"
          f" | overlap={overlap} | omega={omega}"
          f" | solver={solver} | isocp={isocp}")
    for i in range(1, partitions + 1):
        w = windows[i]
        print(f"  Win {i}: core=[{w['cs']},{w['ce']}]  window=[{w['ws']},{w['we']}]")

    t_parse = time.perf_counter()
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
        d['prev_B']    = dict(d['b0'])
        d['term_B']    = dict(d['b0'])
        d['term_Pc']   = {j: 0 for j in d['Bset']}
        d['term_Pd']   = {j: 0 for j in d['Bset']}
        d['term_dual'] = {j: 0 for j in d['Bset']}

        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi)
            d['I_ang'] = angles['I_ang']
        window_data_map[i] = d
    t_parse_done = time.perf_counter()
    print(f"  Parse done in {t_parse_done - t_parse:.2f}s")

    b_global_init = dict(window_data_map[1]['b0'])

    t0 = time.perf_counter()
    vals, B_final, converged, timing = solve_OTD(
        window_data_map, windows, b_global_init,
        obj, solver, alpha_scd,
        non_linear, isocp, p_control, integer, single_battery_variable,
        max_iters=max_iters, tol=tol, omega=omega,
    )
    t_total = time.perf_counter() - t0

    actual_obj = eval_actual_obj(vals, window_data_map, alpha_scd, price)
    print(f"\n{'='*55}")
    print(f"  Solver       : {solver} | isocp={isocp} | P={partitions}")
    print(f"  Parse time   : {t_parse_done - t_parse:.2f}s")
    print(f"  OTD total    : {t_total:.2f}s  (parse NOT included)")
    print(f"  Converged    : {converged}")
    print(f"  Objective    : {actual_obj:.6f}")
    print(f"{'='*55}")
    # plot_battery_soc(OTDVals=vals)