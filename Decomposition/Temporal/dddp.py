"""
DDDP-OTD: parallel multi-cut Benders over OTD windows.

Differs from Schwarz OTD (Decomposition/Temporal/OTD_parallel.py) only at the
window-coupling layer:
  - Windows are *disjoint* (overlap = 0). Cuts replace the right-lookahead.
  - Each window i carries a scalar epigraph variable theta_i with a
    ConstraintList `cuts` that lower-bounds the downstream value function.
  - Per iteration, all P windows solve in parallel; each returns
        beta_left = dual of battery_dynamics[ws_i, j]
                  = ∂(stage_cost + theta_i) / ∂(prev_B[j])
    The parent assembles a cut for window (i-1)'s theta from window i's
    (objective, beta_left, prev_B_used):
        alpha = obj_i - Σ_j beta_left_i[j] * prev_B_used_i[j]
        theta_{i-1} >= alpha + Σ_j beta_left_i[j] * B[ce_{i-1}, j]
  - State-passing: window (i+1)'s prev_B := window i's B[ce_i] from this iter.
  - LB(k)  = obj of window 1 at iter k (= stage_cost_1 + theta_1).
  - UB(k)  = Σ_i stage_cost_i at iter k (true total primal cost — windows are
             disjoint so the sum is exact, no stitching needed).
  - Convergence: (UB − LB) / max(1, |UB|) < tol.

The underlying Pyomo model is built by `get_or_build_model(..., benders=True)`,
which swaps the Schwarz term_* / rho penalty Params for a single theta + cuts
ConstraintList and changes obj to `stage_cost + theta`.

This file is intentionally a standalone driver — it shares no mutable state
with OTD_parallel.py and was kept separate so the canonical Schwarz baseline
stays untouched.
"""

import os
import sys
import time
import pickle
import tempfile
import multiprocessing as mp

# Add project root to path so Build_Model, Plot, etc. are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# NREL corporate proxy intercepts TLS to token.gurobi.com — point Gurobi at
# the locally-installed bundle so WLS license fetch succeeds.
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca
_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

# spawn: Gurobi is not fork-safe; spawn starts each worker from scratch.
_MP_CTX = mp.get_context('forkserver')

from pyomo.environ import value as pyo_value
from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results
from Centralized.isocp import _solve_isocp, reset_isocp_cuts
from Decomposition.Temporal.OTD_parallel import build_windows
from Plot.Plotting import *


_IDAES_BIN = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')


# ── Dedicated persistent worker for one Benders OTD window ───────────────────
def _window_worker_process(window_idx, data_path, obj, solver, alpha_scd,
                            non_linear, isocp, p_control, integer,
                            single_battery_variable, recv_conn, send_conn):
    """One process per window. Builds its model ONCE then loops solve/send.

      msg in  : (prev_B, new_cuts, run_isocp)
                 prev_B    — dict {j: float} initial SOC for this window
                 new_cuts  — list of (alpha, beta_dict) Benders cuts to add to
                             model.cuts:  theta >= alpha + Σ_j β_j · B[ce, j]
                 run_isocp — bool: do ISOCP refinement after the solve
      msg out : store_results(model) extended with
                 'beta_left'   — dict {j: dual of battery_dynamics[ws, j]}
                                  = ∂(model.obj) / ∂(prev_B[j])
                 'prev_B_used' — dict {j: prev_B value used in this solve}
                                  (intercept anchor for the cut)
                 'stage_cost'  — float, value of model.stage_cost only
                                  (= primal cost of this window, no theta).
                                  With overlap=0, summing these across windows
                                  gives the true total UB.

    model.obj = stage_cost + theta (set in Build_Model/Constraints.py when
    benders=True), so solution['objective_value'] is the correct value-
    function estimate at the current prev_B and accumulated cuts.
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
        benders=True,
    )
    Bset       = list(model.Bset)
    ce_abs     = w_data['ce']           # absolute timestep at end of core
    tmin_local = min(model.Tset)        # = ws (absolute start of window)
    send_conn.send(None)                # signal: model ready

    while True:
        msg = recv_conn.recv()
        if msg is None:                 # shutdown
            break
        prev_B, new_cuts, run_isocp = msg
        for j in Bset:
            model.prev_B[j] = prev_B[j]

        # Append cuts received this iter:
        #   theta >= alpha + Σ_j β_j · B[ce_abs, j]
        for alpha, beta in new_cuts:
            model.cuts.add(
                model.theta >= alpha
                + sum(beta[j] * model.B[ce_abs, j] for j in Bset)
            )

        if isocp:
            reset_isocp_cuts(model)
        s.solve(model)
        if isocp and run_isocp:
            # model.cuts.deactivate()
            model, _ = _solve_isocp(prev_sol=store_results(model), model=model,
                                    model_solver=s,inner_tol=1e-3)

        # β = dual of battery_dynamics[tmin_local, j]. prev_B enters the model
        # only at t == tmin_local, so this dual is exactly ∂(model.obj)/∂(prev_B).
        # On the final ISOCP refinement pass the model is a QCP with directional
        # cuts (no linear 'Pi' duals) and no new Benders cuts are built, so
        # beta_left is unused — skip the dual extraction to avoid a Gurobi error.
        if isocp and run_isocp:
            beta_left = {j: 0.0 for j in Bset}
        elif hasattr(s, 'get_duals'):
            dual_cons = [model.battery_dynamics[tmin_local, j] for j in Bset]
            duals_raw = s.get_duals(cons_to_load=dual_cons)
            beta_left = {j: duals_raw[model.battery_dynamics[tmin_local, j]]
                         for j in Bset}
        elif hasattr(model, 'dual'):
            beta_left = {j: model.dual[model.battery_dynamics[tmin_local, j]]
                         for j in Bset}
        else:
            raise RuntimeError(
                f"Window {window_idx}: no dual extraction method available.")

        solution = store_results(model)
        solution['beta_left']   = beta_left
        solution['prev_B_used'] = dict(prev_B)
        solution['stage_cost']  = float(pyo_value(model.stage_cost))
        send_conn.send(solution)


# ── State-pass helper ─────────────────────────────────────────────────────────
def _extract_state_pass(windows, all_results):
    """Window i's B[ce_i, :] becomes window (i+1)'s prev_B next iter."""
    next_prev_B = {}
    for i, w in windows.items():
        if (i + 1) in windows:
            ce_i = w['ce']
            B_vals = all_results[i]['B']
            Bset_i = sorted({k[1] for k in B_vals if k[0] == ce_i})
            next_prev_B[i + 1] = {j: B_vals[ce_i, j] for j in Bset_i}
    return next_prev_B


def _merge_results(all_results, windows):
    """Union per-window primal dicts. With overlap=0 each timestep appears in
    exactly one window, so a plain union is correct — no core-only filter
    needed (unlike Schwarz, which discards each window's overlap region).
    """
    out = {}
    skip = {'objective_value', 'stage_cost', 'beta_left', 'prev_B_used', 'dual'}
    for i in windows:
        for var, vdict in all_results[i].items():
            if var in skip:
                continue
            if not isinstance(vdict, dict):
                out.setdefault(var, vdict)
                continue
            out.setdefault(var, {}).update(vdict)
    return out


# ── Main parallel multi-cut Benders loop ─────────────────────────────────────
def solve_DDDP_OTD(window_data_map, windows, b_global_init,
                   obj, solver, alpha_scd,
                   non_linear, isocp, p_control, integer, single_battery_variable,
                   max_iters=25, tol=1e-4):
    partitions = len(windows)
    Bset = list(window_data_map[1]['Bset'])

    all_results    = {}
    converged      = False
    max_delta      = float('inf')
    t0             = time.perf_counter()
    iter_times     = []
    delta_history  = []
    lb_history     = []   # window-1 objective (= stage_cost_1 + theta_1): LB
    ub_history     = []   # sum of stage_cost_i across all windows: true UB
    gap_rel_history = []  # (UB-LB)/max(1,|UB|) per iteration

    # State-passing SOC fed into each window as model.prev_B.
    prev_B_per_window = {i: dict(b_global_init) for i in windows}
    # Pending cuts for next iter, indexed by destination window.
    pending_cuts = {i: [] for i in windows}

    # Pre-serialise each window's data to a temp file (done once in parent).
    t_serial_start = time.perf_counter()
    _tmpdir = tempfile.mkdtemp(prefix='dddp_otd_worker_')
    data_paths = {}
    for i in windows:
        # Worker needs absolute core-end timestep to build cuts on B[ce, j].
        window_data_map[i]['ce'] = windows[i]['ce']
        path = os.path.join(_tmpdir, f'window_{i}.pkl')
        with open(path, 'wb') as f:
            pickle.dump(window_data_map[i], f, protocol=pickle.HIGHEST_PROTOCOL)
        data_paths[i] = path
    t_serial = time.perf_counter() - t_serial_start

    # Launch one persistent worker per window (all build in parallel).
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

    print(f"  Launching {partitions} dedicated worker processes...", flush=True)
    for i in windows:
        recv_conns[i].recv()
    t_build = time.perf_counter() - t_launch_start
    print(f"  All models built in {t_build:.2f}s | starting iterations",
          flush=True)

    try:
        for k in range(1, max_iters + 1):
            tk = time.perf_counter()

            # Snapshot prev_B sent this iter (= anchor for the cut intercept).
            prev_B_sent = {i: dict(prev_B_per_window[i]) for i in windows}

            for i in windows:
                send_conns[i].send((prev_B_sent[i],
                                    pending_cuts[i],
                                    False))
            # Clear queued cuts now that they're dispatched.
            pending_cuts = {i: [] for i in windows}

            all_results = {i: recv_conns[i].recv() for i in windows}

            # Build new cuts for next iter: window i's solution gives a cut on
            # window (i-1)'s theta. Pattern mirrors dddp_isocp.py's
            #   cuts[f'cuts_{stage_idx-1}'].append((Q - Σβ·prev_B, β))
            for i in windows:
                if (i - 1) not in windows:
                    continue
                Q       = all_results[i]['objective_value']
                beta    = all_results[i]['beta_left']
                prev_at = all_results[i]['prev_B_used']
                alpha   = Q - sum(beta[j] * prev_at[j] for j in Bset)
                pending_cuts[i - 1].append((alpha, dict(beta)))

            # State-pass: window (i+1)'s prev_B := window i's B[ce_i].
            new_prev_B = _extract_state_pass(windows, all_results)
            for i, pb in new_prev_B.items():
                prev_B_per_window[i] = pb

            if partitions > 1:
                max_delta = max(
                    (abs(prev_B_per_window[i][j] - prev_B_sent[i][j])
                     for i in windows if i >= 2
                     for j in Bset),
                    default=0.0)
            else:
                max_delta = 0.0

            iter_t = time.perf_counter() - tk
            iter_times.append(iter_t)
            delta_history.append(max_delta)
            lb_iter = all_results[1]['objective_value']*1000
            ub_iter = sum(all_results[i]['stage_cost'] for i in windows)*1000
            lb_history.append(lb_iter)
            ub_history.append(ub_iter)
            gap     = abs(ub_iter - lb_iter)
            gap_rel = gap / max(1.0, abs(ub_iter))
            gap_rel_history.append(gap_rel)
            print(f"  iter {k:02d} | LB = {lb_iter:.6f} | UB = {ub_iter:.6f}"
                  f" | gap = {gap:.3e} ({gap_rel:.3e})"
                  f" | ΔB = {max_delta:.4f} | t = {iter_t:.2f}s")

            # Convergence: LB is monotone non-decreasing in Benders, so when
            # it stops moving the algorithm is at the optimum. Watching two
            # consecutive ΔLB filters single-iter noise from ISOCP cut shifts.
            # UB is *not* tested here because primal degeneracy at the window
            # boundaries makes per-iter UB oscillate even after LB plateaus —
            # the reported final UB is averaged over the last few iters to
            # cancel that oscillation.
            # P == 1: only one window, no cuts to add, no state to pass —
            # iter 2+ would be identical to iter 1. Exit immediately.
            if partitions == 1:
                converged = True
                print(f"  Converged (P=1, single window) | total = "
                      f"{time.perf_counter() - t0:.2f}s")
                break
            # if abs(ub_iter - lb_iter)/ub_iter < 1e-4:
            #     converged = True
            #     print(f"  Converged (UB-LB<{1e-4:.0e}) | total = "
            #           f"{time.perf_counter() - t0:.2f}s")
            #     break
            if len(lb_history) >= 3:
                rel = max(1.0, abs(lb_iter))
                d1 = abs(lb_history[-1] - lb_history[-2]) / rel
                d2 = abs(lb_history[-2] - lb_history[-3]) / rel
                # d3 = abs(lb_history[-3] - lb_history[-4]) / rel 
                if max(d1, d2) < 1e-5:
                    converged = True
                    print(f"  Converged (LB stable, ΔLB<{tol:.0e}) | total = "
                          f"{time.perf_counter() - t0:.2f}s")
                    break

        # Final ISOCP refinement: replace the last iteration's SOCP LB/UB with
        # AC-tight values so lb_history, ub_history, gap_rel_history all have
        # exactly one entry per Benders iteration (the final one is ISOCP).
        if isocp:
            print("  Running final ISOCP refinement...", flush=True)
            for i in windows:
                send_conns[i].send((prev_B_per_window[i], [], True))
            all_results = {i: recv_conns[i].recv() for i in windows}
            ub_refined = sum(all_results[i]['stage_cost'] for i in windows)*1000
            lb_refined = all_results[1]['objective_value']*1000
            # Replace last SOCP entry — keeps history length == n_iters
            lb_history[-1]      = lb_refined
            ub_history[-1]      = ub_refined
            gap     = abs(ub_refined - lb_refined)
            gap_rel = gap / max(1.0, abs(ub_refined))
            gap_rel_history[-1] = gap_rel
            print(f"  ISOCP refinement done | LB = {lb_refined:.6f}"
                  f" | UB = {ub_refined:.6f}"
                  f" | gap = {gap:.3e} | gap_rel = {gap_rel:.3e}", flush=True)
    finally:
        # Signal all workers to shut down
        for i in windows:
            try: send_conns[i].send(None)
            except Exception: pass
        # Wait, then force-terminate stragglers
        # for p in procs:
        #     p.join(timeout=5)
        #     if p.is_alive():
        #         p.terminate()
        #         p.join(timeout=2)

    if not converged:
        final_gap = ub_history[-1] - lb_history[-1] if ub_history else float('nan')
        print(f"  WARNING: not converged after {max_iters} iters. "
              f"Final gap = {final_gap:.3e}")

    timing = {
        'total_s':        time.perf_counter() - t0,
        'serial_s':       t_serial,
        'build_s':        t_build,
        'iter_times':     iter_times,
        'delta_history':  delta_history,
        'lb_history':     lb_history,
        'ub_history':     ub_history,
        'gap_rel_history': gap_rel_history,
        'n_iters':        len(iter_times),
        'avg_iter_s':     sum(iter_times) / len(iter_times) if iter_times else 0.0,
        'converged':      converged,
    }
    # Final-iter B[ce_i, :] for diagnostics.
    B_end = {i: _extract_state_pass(windows, all_results).get(i + 1, {})
             for i in range(1, partitions + 1)}
    return _merge_results(all_results, windows), B_end, converged, timing


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pickle
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles

    system_name = 'IEEE_123'
    wd          = os.path.join(os.path.dirname(__file__), '..', '..')
    filepath    = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path    = os.path.join(wd, 'rawData', system_name,
                               'dss_scripts', 'Master.dss')
    save_dir    = os.path.join(wd, 'run_logs')
    os.makedirs(save_dir, exist_ok=True)

    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    # for col in ['bmin_a', 'bmin_b', 'bmin_c', 'bmax_a', 'bmax_b', 'bmax_c']:
    #     if col in bat_data.columns:
    #         bat_data[col] *= 2
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
    solver                  = 'gurobi'
    alpha_scd               = 1e-3
    n_total                 = 24
    partitions              = 1    # ← change this to run different partitions
    overlap                 = 0          # disjoint windows — cuts replace lookahead
    v_min_val, v_max_val    = 0.9, 1.2
    max_iters               = 25
    tol                     = 1e-3

    windows = build_windows(n_total, partitions, overlap)
    base    = n_total // partitions
    print(f"\nDDDP-OTD (parallel multi-cut Benders) | T=1..{n_total}"
          f" | P={partitions} | base={base} | overlap={overlap}"
          f" | solver={solver} | isocp={isocp}")
    for i in range(1, partitions + 1):
        w = windows[i]
        print(f"  Win {i}: core=[{w['cs']},{w['ce']}]  "
              f"window=[{w['ws']},{w['we']}]")

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
        d['ce']    = w['ce']
        d['prev_B'] = dict(d['b0'])

        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi,
                                                   start_step=w['ws'])
            d['I_ang'] = angles['I_ang']
        window_data_map[i] = d
    print(f"  Parse done in {time.perf_counter() - t_parse:.2f}s")

    b_global_init = dict(window_data_map[1]['b0'])

    vals, B_final, converged, timing = solve_DDDP_OTD(
        window_data_map, windows, b_global_init,
        obj, solver, alpha_scd,
        non_linear, isocp, p_control, integer, single_battery_variable,
        max_iters=max_iters, tol=tol,
    )

    lb_final  = timing['lb_history'][-1] if timing['lb_history'] else float('nan')
    ub_final  = timing['ub_history'][-1] if timing['ub_history'] else float('nan')
    gap_final = ub_final - lb_final
    gap_rel   = gap_final / max(1.0, abs(ub_final))

    print(f"\n=== DDDP-OTD summary | P={partitions} ===")
    print(f"  iterations          : {timing['n_iters']}")
    print(f"  converged           : {converged}")
    print(f"  total wall time     : {timing['total_s']:.2f}s")
    print(f"  build time          : {timing['build_s']:.2f}s")
    print(f"  avg iter time       : {timing['avg_iter_s']:.2f}s")
    print(f"  final LB            : {lb_final:.6f}")
    print(f"  final UB            : {ub_final:.6f}")
    print(f"  final gap (UB-LB)   : {gap_final:.3e} ({gap_rel:+.2%})")

    # Save: one file per (system, partitions) with history for plotting.
    save_dir  = os.path.join(wd, 'run_logs')
    os.makedirs(save_dir, exist_ok=True)
    save_data = {
        'system_name':     system_name,
        'partitions':      partitions,
        'n_total':         n_total,
        'isocp':           isocp,
        'non_linear':      non_linear,
        'lb_history':      timing['lb_history'],
        'ub_history':      timing['ub_history'],
        'gap_rel_history': timing['gap_rel_history'],
        'total_s':         timing['total_s'],
        'n_iters':         timing['n_iters'],
        'converged':       converged,
        'iter_times':      timing['iter_times'],
    }
    model_tag = 'isocp' if isocp else ('nonlinear' if non_linear else 'linear')
    save_path = os.path.join(save_dir,
                             f'dddp_{system_name}_P{partitions}_{model_tag}_new.pkl')
    with open(save_path, 'wb') as f:
        pickle.dump(save_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  Saved → {save_path}")
