"""Generate IEEE Transactions convergence figure for DDDP-OTD (Benders).

Runs two configurations back-to-back on IEEE 123-bus, T=24:
    1. Linear BFM   (isocp=False)
    2. ISOCP        (isocp=True)

Produces a double-column (7.16 in) PDF with:
    (a) UB / LB objective trajectories
    (b) Relative optimality gap on a log scale

Usage:
    python plot_dddp_otd_paper.py

Output: dddp_otd_convergence.pdf  (same directory)
"""

if __name__ == '__main__':
    import os
    import time
    import warnings
    import pandas as pd

    # Suppress the harmless macOS forkserver resource_tracker semaphore warning
    # that fires when daemon worker processes are reaped at interpreter exit.
    warnings.filterwarnings(
        'ignore',
        message=r'resource_tracker.*leaked semaphore',
        category=UserWarning,
    )

    # ── env setup (mirrors main.py) ──────────────────────────────────────────
    _grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
    if os.path.exists(_grb_ca):
        os.environ['GRB_CAFILE'] = _grb_ca
    _idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
    if _idaes_bin not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles
    from Decomposition.Temporal.dddp import solve_DDDP_OTD
    from Decomposition.Temporal.OTD_parallel import build_windows
    from Plot.Plotting import plot_dddp_otd_convergence

    # ── problem config ───────────────────────────────────────────────────────
    system_name = 'IEEE_123'
    n_total     = 24
    partitions  = 6
    solver      = 'gurobi'
    alpha_scd   = 1e-3
    max_iters   = 25
    tol         = 1e-3
    obj         = cost_minimize_with_scd

    wd       = os.path.dirname(os.path.abspath(__file__))
    fp       = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')

    def load_data(isocp=False):
        bus_data    = pd.read_csv(os.path.join(fp, 'bus_data.csv'))
        branch_data = pd.read_csv(os.path.join(fp, 'branch_data.csv'))
        gen_data    = pd.read_csv(os.path.join(fp, 'gen_data.csv'))
        bat_data    = pd.read_csv(os.path.join(fp, 'battery_data.csv'))
        loadshape   = pd.read_csv(os.path.join(fp, 'default_loadshape.csv'))
        pvshape     = pd.read_csv(os.path.join(fp, 'pv_loadshape.csv'))
        price       = 0.15 * loadshape['M'] + 0.15

        overlap = 0  # DDDP-OTD uses disjoint windows; cuts replace the lookahead
        windows = build_windows(n_total, partitions, overlap)

        window_data_map = {}
        for i in range(1, partitions + 1):
            w = windows[i]
            d = parse_all_data_phase_aware(
                bus_data, branch_data, gen_data, bat_data,
                loadshape=loadshape, pvshape=pvshape,
                price=price, start_step=w['ws'], n_steps=w['n'],
            )
            d['v_min']     = {k: 0.9 for k in d['v_min']}
            d['v_max']     = {k: 1.2 for k in d['v_max']}
            d['ws']        = w['ws']
            d['we']        = w['we']
            d['prev_B']    = dict(d['b0'])
            d['term_B']    = dict(d['b0'])
            d['term_Pc']   = {j: 0 for j in d['Bset']}
            d['term_Pd']   = {j: 0 for j in d['Bset']}
            d['term_dual'] = {j: 0 for j in d['Bset']}
            if isocp:
                angles     = initialize_current_angles(d, dss_path, multi=True)
                d['I_ang'] = angles['I_ang']
            window_data_map[i] = d

        b0 = dict(window_data_map[1]['b0'])
        return window_data_map, windows, b0

    # ── run both variants and collect timing dicts ───────────────────────────
    runs = []
    configs = [
        dict(label='Linear', isocp=False, color='#000000', linestyle='-'),
        dict(label='ISOCP',      isocp=True,  color='#1f77b4', linestyle='--'),
    ]

    for cfg in configs:
        label  = cfg['label']
        isocp  = cfg['isocp']
        print(f"\n{'='*55}")
        print(f"  Running DDDP-OTD  |  {label}  |  solver={solver}")
        print('='*55)
        wdm, windows, b0 = load_data(isocp=isocp)
        t0 = time.perf_counter()
        _, _, converged, timing = solve_DDDP_OTD(
            wdm, windows, b0, obj, solver, alpha_scd,
            non_linear=False, isocp=isocp,
            p_control=False, integer=False, single_battery_variable=False,
            max_iters=max_iters, tol=tol,
        )
        elapsed = time.perf_counter() - t0
        print(f"  {label} | converged={converged} | iters={timing['n_iters']}"
              f" | total={elapsed:.1f}s | avg iter={timing['avg_iter_s']:.1f}s")
        runs.append({
            'label':      label,
            'lb_history': timing['lb_history'],
            'ub_history': timing['ub_history'],
            'color':      cfg['color'],
            'linestyle':  cfg['linestyle'],
        })

    # ── generate figure ──────────────────────────────────────────────────────
    out = os.path.join(wd, 'dddp_otd_convergence.pdf')
    plot_dddp_otd_convergence(*runs, out_path=out, tol=tol,
                               obj_scale=1000, obj_unit=r'\$')
    print(f"\nFigure saved: {out}")
