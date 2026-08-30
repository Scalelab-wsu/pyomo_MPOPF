"""
Temporal ADMM: window-level ADMM temporal decomposition.

Reference: R. Pinto, R.J. Bessa, J. Sumaili, M.A. Matos,
"Distributed multi-period three-phase optimal power flow using temporal
neighbors," Electric Power Systems Research, 182 (2020) 106228.

The Pinto paper decomposes spatially (by bus) with temporal coupling via the
'temporal neighbor' concept.  Here we adapt the same ADMM mechanics to
decompose TEMPORALLY into P disjoint windows, solving the full three-phase
OPF within each window.  This gives a direct parallel comparison to DDDP-OTD.

ADMM formulation (Boyd et al., sec 7.1 consensus):
  Boundary i exists for i = 1 .. P-1, between windows i and i+1.

  Two agents share consensus variable z_i:
    Agent A — window i :   x_A = B[ce_i, j]   (terminal SOC)
    Agent B — window i+1:  x_B = B_init_{i+1}[j]  (initial SOC, free Var)

  Window subproblem (all P windows solved in parallel each iteration):

    min  f_i(OPF)
       + (rho_in /2) * ||B_init_i - z_{i-1} + u_in_i||^2    [left bdry]
       + (rho_out/2) * ||B[ce_i]  - z_i     + u_out_i||^2   [right bdry]

    Window 1   : rho_in  = 0  (left  boundary is the fixed global init SOC)
    Window P   : rho_out = 0  (right boundary handled by final_soc constraint)

  Consensus update (closed form):
    z_i = ((B[ce_i] + u_out_i) + (B_init_{i+1} + u_in_{i+1})) / 2

  Scaled dual update (u = lambda/rho):
    u_out_i    += B[ce_i]        - z_i
    u_in_{i+1} += B_init_{i+1}  - z_i

  Stopping criteria (Pinto eq. 34-35):
    primal residual: max_i  ||B[ce_i] - B_init_{i+1}||_inf  < eps_p
    dual   residual: max_i  rho * ||z_i^k - z_i^{k-1}||_inf < eps_d
"""

import os
import sys
import time
import pickle
import tempfile
import multiprocessing as mp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca
_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

_MP_CTX = mp.get_context('forkserver')

from pyomo.environ import value as pyo_value
from Build_Model.Constraints import get_or_build_model
from Build_Model.store import store_results
from Centralized.isocp import _solve_isocp, reset_isocp_cuts
from Decomposition.Temporal.OTD_parallel import build_windows
from Plot.Plotting import *


_IDAES_BIN = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')

# ── appsi-safe solve (mirrors the _safe_solve pattern documented in repo memory)
def _admm_safe_solve(s, model):
    """Wrap appsi solve to avoid RuntimeError on infeasibility."""
    s.config.load_solution = False
    try:
        res = s.solve(model)
        tc  = getattr(res, 'termination_condition', None)
        tc_str = tc.name if hasattr(tc, 'name') else str(tc)
        feasible = tc_str in ('optimal', 'locallyOptimal', 'globallyOptimal', 'unknown')
        if feasible:
            s.load_vars()
        return tc_str, feasible
    except RuntimeError:
        return 'infeasible', False
    finally:
        s.config.load_solution = True
def _admm_worker_process(window_idx, data_path, obj, solver, alpha_scd,
                         non_linear, isocp, p_control, integer,
                         single_battery_variable, recv_conn, send_conn):
    """One process per window.  Loops indefinitely until it receives None.

    msg in : (z_in, u_in, z_out, u_out, run_isocp)
             Each z/u is a dict {j: float}.  When run_isocp=True the worker
             fixes B_init to z_in, zeroes rho, runs _solve_isocp, then
             restores the model for future iterations.
    msg out: store_results dict extended with
             'B_init'      — {j: float} value of model.B_init[j]
             'B_out'       — {j: float} value of model.B[ce_abs, j]
             'stage_cost'  — float  OPF cost without ADMM penalty
    """
    if _IDAES_BIN not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _IDAES_BIN + os.pathsep + os.environ.get('PATH', '')

    with open(data_path, 'rb') as f:
        w_data = pickle.load(f)

    is_first = w_data['is_first']
    is_last  = w_data['is_last']
    ce_abs   = w_data['ce']

    model, s = get_or_build_model(
        w_data, obj, solver=solver, alpha_scd=alpha_scd,
        stage_idx=(w_data['ws'], w_data['we']),
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
        admm=True,
    )
    Bset = list(model.Bset)

    # QcpDual=1 is incompatible with QCQP during ADMM iterations; disable it.
    # Method=2 + BarHomogeneous=1: barrier solver, robust on ill-conditioned QCQP.
    if hasattr(s, '_solver_options'):
        s._solver_options['QcpDual'] = 0
        s._solver_options['Method'] = 2
        s._solver_options['BarHomogeneous'] = 1

    # Window 1: no left boundary — rho_in stays 0 permanently.
    # Window P: no right boundary — rho_out stays 0 permanently.
    if is_first:
        model.admm_rho_in.set_value(0.0)
    if is_last:
        model.admm_rho_out.set_value(0.0)

    send_conn.send(None)   # signal: model ready

    while True:
        msg = recv_conn.recv()
        if msg is None:
            break
        z_in, u_in, z_out, u_out, run_isocp = msg

        for j in Bset:
            model.admm_z_in[j]  = z_in[j]
            model.admm_u_in[j]  = u_in[j]
            model.admm_z_out[j] = z_out[j]
            model.admm_u_out[j] = u_out[j]

        if isocp:
            reset_isocp_cuts(model)

        s.solve(model)

        if isocp and run_isocp:
            model, _ = _solve_isocp(prev_sol=store_results(model), model=model,
                                    model_solver=s, inner_tol=1e-3, max_inner=30)

        # Pure OPF cost (no ADMM penalty term).
        cost_data = w_data['costshape']
        substation_phase_set = list(model.substation_phase_set)
        stage_cost = sum(
            pyo_value(model.P_subs[t, j, ph]) * cost_data[t]
            for t in model.Tset
            for j, ph in substation_phase_set
        )

        solution = store_results(model)
        solution['B_init']     = {j: pyo_value(model.B_init[j]) for j in Bset}
        solution['B_out']      = {j: pyo_value(model.B[ce_abs, j]) for j in Bset}
        solution['stage_cost'] = stage_cost
        send_conn.send(solution)


# ── Stitch per-window primals into a single result dict ───────────────────────
def _merge_admm_results(all_results, windows):
    out = {}
    skip = {'objective_value', 'stage_cost', 'B_init', 'B_out'}
    for i in windows:
        for var, vdict in all_results[i].items():
            if var in skip:
                continue
            if not isinstance(vdict, dict):
                out.setdefault(var, vdict)
                continue
            out.setdefault(var, {}).update(vdict)
    return out


# ── Main temporal ADMM loop ───────────────────────────────────────────────────
def solve_temporal_ADMM(window_data_map, windows, b_global_init,
                        obj, solver, alpha_scd,
                        non_linear, isocp, p_control, integer,
                        single_battery_variable,
                        rho=1.0, max_iters=100,
                        eps_p=1e-3, eps_d=1e-3):
    """Solve multi-period OPF via temporal ADMM (Pinto et al. 2020 adapted).

    Parameters
    ----------
    rho      : ADMM penalty weight (same for in- and out-boundaries).
    eps_p    : primal residual tolerance (max SOC mismatch at boundaries).
    eps_d    : dual residual tolerance (rho * max change in consensus z).
    """
    P    = len(windows)
    Bset = list(window_data_map[1]['Bset'])

    # ── Boundary index set: boundary i couples window i (out) and i+1 (in) ──
    boundaries = list(range(1, P))   # i = 1 .. P-1

    # ── Initialize consensus z and scaled duals u (Boyd et al. sec 3.1.1) ───
    # z[i][j] : agreed SOC at boundary i
    # u_out[i][j] : scaled dual for window i's terminal SOC at boundary i
    # u_in[i][j]  : scaled dual for window i's initial  SOC at boundary i-1
    z     = {i: dict(b_global_init) for i in boundaries}
    u_out = {i: {j: 0.0 for j in Bset} for i in boundaries}         # keyed by left window
    u_in  = {i: {j: 0.0 for j in Bset} for i in range(2, P + 1)}   # keyed by right window

    all_results     = {}
    converged       = False
    t0              = time.perf_counter()
    iter_times      = []
    prim_hist       = []
    dual_hist       = []
    cost_hist       = []

    # Pre-serialise window data.
    t_serial_start = time.perf_counter()
    _tmpdir    = tempfile.mkdtemp(prefix='temporal_admm_worker_')
    data_paths = {}
    for i in windows:
        window_data_map[i]['ce']       = windows[i]['ce']
        window_data_map[i]['is_first'] = (i == 1)
        window_data_map[i]['is_last']  = (i == P)
        # Set rho values in the data dict (used to initialise Params in worker).
        window_data_map[i]['admm_rho'] = rho
        path = os.path.join(_tmpdir, f'admm_window_{i}.pkl')
        with open(path, 'wb') as f:
            pickle.dump(window_data_map[i], f, protocol=pickle.HIGHEST_PROTOCOL)
        data_paths[i] = path
    t_serial = time.perf_counter() - t_serial_start

    # Launch persistent workers.
    send_conns, recv_conns = {}, {}
    procs = []
    t_launch_start = time.perf_counter()
    for i in windows:
        p_recv, c_send = _MP_CTX.Pipe(duplex=False)
        c_recv, p_send = _MP_CTX.Pipe(duplex=False)
        proc = _MP_CTX.Process(
            target=_admm_worker_process,
            args=(i, data_paths[i], obj, solver, alpha_scd,
                  non_linear, isocp, p_control, integer,
                  single_battery_variable, c_recv, c_send),
            daemon=True,
        )
        proc.start()
        send_conns[i] = p_send
        recv_conns[i] = p_recv
        procs.append(proc)

    print(f"  Launching {P} ADMM worker processes...", flush=True)
    for i in windows:
        recv_conns[i].recv()   # wait for model-ready signal
    t_build = time.perf_counter() - t_launch_start
    print(f"  All models built in {t_build:.2f}s | rho={rho} | "
          f"eps_p={eps_p} eps_d={eps_d}", flush=True)

    # Set rho in all worker models (mutable Params).
    # Sent as part of the first z/u message.

    try:
        for k in range(1, max_iters + 1):
            tk = time.perf_counter()

            # Send current z and u to each window.
            for i in windows:
                # Left boundary of window i  (boundary i-1, if it exists)
                if i > 1:
                    zi_in  = z[i - 1]
                    ui_in  = u_in[i]
                else:
                    zi_in  = dict(b_global_init)   # unused (rho_in=0 for win 1)
                    ui_in  = {j: 0.0 for j in Bset}

                # Right boundary of window i  (boundary i, if it exists)
                if i < P:
                    zi_out = z[i]
                    ui_out = u_out[i]
                else:
                    zi_out = dict(b_global_init)   # unused (rho_out=0 for win P)
                    ui_out = {j: 0.0 for j in Bset}

                # First iteration: also propagate rho into the model Params.
                # Workers initialise admm_rho_in / admm_rho_out at build time
                # (is_first / is_last flags), so no explicit rho message needed.
                send_conns[i].send((zi_in, ui_in, zi_out, ui_out, False))

            all_results_raw = {i: recv_conns[i].recv() for i in windows}
            # None means worker infeasibility — skip consensus for this iteration.
            if any(r is None for r in all_results_raw.values()):
                failed = [i for i, r in all_results_raw.items() if r is None]
                print(f"  iter {k}: windows {failed} infeasible — skipping",
                      flush=True)
                continue
            all_results = all_results_raw

            B_out  = {i: all_results[i]['B_out']  for i in windows}
            B_init = {i: all_results[i]['B_init'] for i in windows}

            z_prev = {i: dict(z[i]) for i in boundaries}

            # ── Consensus update (Boyd et al. eq 7.3) ────────────────────────
            # z_i = ((B_out_i + u_out_i) + (B_init_{i+1} + u_in_{i+1})) / 2
            for i in boundaries:
                for j in Bset:
                    z[i][j] = 0.5 * ((B_out[i][j]     + u_out[i][j]) +
                                     (B_init[i + 1][j] + u_in[i + 1][j]))

            # ── Scaled dual update (Boyd et al. eq 3.12) ─────────────────────
            for i in boundaries:
                for j in Bset:
                    u_out[i][j]    += B_out[i][j]     - z[i][j]
                    u_in[i + 1][j] += B_init[i + 1][j] - z[i][j]

            # ── Convergence check (Pinto eq. 34-35) ──────────────────────────
            prim_res = max(
                abs(B_out[i][j] - B_init[i + 1][j])
                for i in boundaries for j in Bset
            ) if boundaries else 0.0

            dual_res = max(
                rho * abs(z[i][j] - z_prev[i][j])
                for i in boundaries for j in Bset
            ) if boundaries else 0.0

            total_cost = sum(all_results[i]['stage_cost'] for i in windows) * 1000

            iter_t = time.perf_counter() - tk
            iter_times.append(iter_t)
            prim_hist.append(prim_res)
            dual_hist.append(dual_res)
            cost_hist.append(total_cost)

            print(f"  iter {k:3d} | prim={prim_res:.4e}  dual={dual_res:.4e} "
                  f"| cost={total_cost:.4f} kWh | {iter_t:.2f}s", flush=True)

            if prim_res < eps_p and dual_res < eps_d:
                converged = True
                break

        # Final ISOCP refinement: fix boundaries to converged z, tighten cones.
        isocp_s = 0.0
        if isocp:
            t_isocp_start = time.perf_counter()
            print("  Running final ISOCP refinement...", flush=True)
            for i in windows:
                if i > 1:
                    zi_in  = z[i - 1];  ui_in  = u_in[i]
                else:
                    zi_in  = dict(b_global_init);  ui_in  = {j: 0.0 for j in Bset}
                if i < P:
                    zi_out = z[i];      ui_out = u_out[i]
                else:
                    zi_out = dict(b_global_init);  ui_out = {j: 0.0 for j in Bset}
                send_conns[i].send((zi_in, ui_in, zi_out, ui_out, True))
            all_results = {i: recv_conns[i].recv() for i in windows}
            cost_isocp  = sum(all_results[i]['stage_cost'] for i in windows) * 1000
            isocp_s     = time.perf_counter() - t_isocp_start
            cost_hist.append(cost_isocp)
            print(f"  ISOCP done | cost = {cost_isocp:.4f} kWh | {isocp_s:.2f}s", flush=True)

    finally:
        for i in windows:
            send_conns[i].send(None)
        for proc in procs:
            proc.join(timeout=10)

    total_time = time.perf_counter() - t0
    merged     = _merge_admm_results(all_results, windows)

    print(f"\n  Temporal ADMM {'CONVERGED' if converged else 'NOT converged'} "
          f"in {k} iters | {total_time:.2f}s total", flush=True)
    if boundaries:
        final_prim = max(
            abs(B_out[i][j] - B_init[i + 1][j])
            for i in boundaries for j in Bset)
        print(f"  Final primal residual: {final_prim:.4e}  "
              f"(tol={eps_p})  converged={converged}", flush=True)

    return merged, converged, total_time, {
        'total_s':    total_time,
        'serial_s':   t_serial,
        'build_s':    t_build,
        'isocp_s':    isocp_s,
        'iter_times': iter_times,
        'prim_hist':  prim_hist,
        'dual_hist':  dual_hist,
        'cost_hist':  cost_hist,
        'n_iters':    k,
        'avg_iter_s': sum(iter_times) / len(iter_times) if iter_times else 0.0,
        'converged':  converged,
        'total_cost': sum(all_results[i]['stage_cost'] for i in windows) * 1000,
    }


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles

    # ── Configuration (mirror dddp_otd.py layout) ────────────────────────────
    system_name             = 'IEEE_9500'
    wd                      = os.path.join(os.path.dirname(__file__), '..', '..')
    filepath                = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path                = os.path.join(wd, 'rawData', system_name,
                                           'dss_scripts', 'Master.dss')
    save_dir                = os.path.join(wd, 'run_logs')
    os.makedirs(save_dir, exist_ok=True)

    obj                     = cost_minimize_with_scd
    multi                   = True
    non_linear              = False
    isocp                   = False
    p_control               = False
    integer                 = False
    single_battery_variable = False
    solver                  = 'gurobi'
    alpha_scd               = 1e-2
    n_total                 = 24
    partitions              = 3     # ← change this to compare partition counts
    v_min_val, v_max_val    = 0.9, 1.2
    rho                     = 1   # ADMM penalty weight
    max_iters               = 150
    eps_p                   = 1e-4   # primal residual tolerance
    eps_d                   = 1e-3   # dual   residual tolerance

    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price          = 0.15 * loadshape_data['M'] + 0.15

    windows = build_windows(n_total, partitions, overlap=0)
    base    = n_total // partitions
    print(f"\nTemporal ADMM (Pinto et al. 2020) | T=1..{n_total}"
          f" | P={partitions} | base={base} | rho={rho}"
          f" | solver={solver} | isocp={isocp} | system={system_name}")
    for i in windows:
        w = windows[i]
        print(f"  Win {i}: core=[{w['cs']},{w['ce']}]  window=[{w['ws']},{w['we']}]")

    print("\nParsing window data...")
    t_parse = time.perf_counter()
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
        if non_linear or isocp:
            angles     = initialize_current_angles(d, dss_path, multi=multi,
                                                   start_step=w['ws'])
            d['I_ang'] = angles['I_ang']
        window_data_map[i] = d
    b_global_init = dict(window_data_map[1]['b0'])
    print(f"  Parse done in {time.perf_counter() - t_parse:.2f}s")

    merged, converged, elapsed, stats = solve_temporal_ADMM(
        window_data_map, windows, b_global_init,
        obj=obj, solver=solver, alpha_scd=alpha_scd,
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
        rho=rho, max_iters=max_iters, eps_p=eps_p, eps_d=eps_d,
    )

    print(f"\n=== Temporal ADMM summary | P={partitions} ===")
    print(f"  iterations          : {stats['n_iters']}")
    print(f"  converged           : {converged}")
    print(f"  total wall time     : {stats['total_s']:.2f}s")
    print(f"  build time          : {stats['build_s']:.2f}s")
    print(f"  avg iter time       : {stats['avg_iter_s']:.2f}s")
    print(f"  ISOCP time          : {stats['isocp_s']:.2f}s")
    print(f"  final cost          : {stats['total_cost']:.4f} kWh")

    save_data = {
        'system_name':  system_name,
        'partitions':   partitions,
        'n_total':      n_total,
        'isocp':        isocp,
        'non_linear':   non_linear,
        'prim_hist':    stats['prim_hist'],
        'dual_hist':    stats['dual_hist'],
        'cost_hist':    stats['cost_hist'],
        'iter_times':   stats['iter_times'],
        'n_iters':      stats['n_iters'],
        'total_s':      stats['total_s'],
        'serial_s':     stats['serial_s'],
        'build_s':      stats['build_s'],
        'isocp_s':      stats['isocp_s'],
        'avg_iter_s':   stats['avg_iter_s'],
        'converged':    stats['converged'],
        'total_cost':   stats['total_cost'],
    }
    model_tag = 'isocp' if isocp else ('nonlinear' if non_linear else 'linear')
    save_path = os.path.join(save_dir,
                             f'tadmm_{system_name}_P{partitions}_{model_tag}_new.pkl')
    with open(save_path, 'wb') as f:
        pickle.dump(save_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  Saved → {save_path}")
