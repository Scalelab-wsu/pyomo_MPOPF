"""Run OTD-Schwarz for IEEE_123 in LP and ISOCP mode and plot boundary-error convergence.

All imports are deferred inside __main__ so that forkserver worker processes that
re-execute this module do not trigger any side-effectful imports at module level.
"""

if __name__ == '__main__':
    import os, time
    import matplotlib
    matplotlib.use('Agg')
    import pandas as pd

    _grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
    if os.path.exists(_grb_ca):
        os.environ['GRB_CAFILE'] = _grb_ca

    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles
    from Decomposition.Temporal.OTD_parallel import solve_OTD, build_windows
    from Plot.Plotting import plot_otd_convergence

    system_name = 'IEEE_123'
    n_total     = 24
    partitions  = 8
    solver      = 'gurobi'
    alpha_scd   = 1e-3
    max_iters   = 20
    tol         = 1e-3

    def load_window_data(system_name='IEEE_123', n_total=24, partitions=8,
                         isocp=False):
        wd       = os.getcwd()
        fp       = os.path.join(wd, 'rawData', system_name, 'csvs')
        dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')

        bus_data    = pd.read_csv(os.path.join(fp, 'bus_data.csv'))
        branch_data = pd.read_csv(os.path.join(fp, 'branch_data.csv'))
        gen_data    = pd.read_csv(os.path.join(fp, 'gen_data.csv'))
        bat_data    = pd.read_csv(os.path.join(fp, 'battery_data.csv'))
        loadshape   = pd.read_csv(os.path.join(fp, 'default_loadshape.csv'))
        pvshape     = pd.read_csv(os.path.join(fp, 'pv_loadshape.csv'))
        price       = 0.15 * loadshape['M'] + 0.15

        overlap = 1
        windows = build_windows(n_total, partitions, overlap)

        window_data_map = {}
        for i in range(1, partitions + 1):
            w = windows[i]
            d = parse_all_data_phase_aware(
                bus_data, branch_data, gen_data, bat_data,
                loadshape=loadshape, pvshape=pvshape,
                price=price, start_step=w['ws'], n_steps=w['n'])
            d['v_min'] = {k: 0.9 for k in d['v_min']}
            d['v_max'] = {k: 1.2 for k in d['v_max']}
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

        b_global_init = dict(window_data_map[1]['b0'])
        return window_data_map, windows, b_global_init

    histories = {}

    for isocp, label in [(False, 'LP'), (True, 'ISOCP')]:
        print(f"\n{'='*50}")
        print(f"Running OTD  isocp={isocp}  ({label})")
        print('='*50)
        t0 = time.perf_counter()
        wdm, windows, b0 = load_window_data(system_name, n_total, partitions, isocp=isocp)
        _, _, _, timing = solve_OTD(
            wdm, windows, b0,
            cost_minimize_with_scd, solver, alpha_scd,
            non_linear=False, isocp=isocp,
            p_control=False, integer=False, single_battery_variable=False,
            max_iters=max_iters, tol=tol,
        )
        print(f"  {label} done in {time.perf_counter() - t0:.1f}s | "
              f"converged={timing['converged']} | iters={timing['n_iters']}")
        histories[label] = timing['delta_history']

    plot_otd_convergence(
        ('LP',    list(range(1, len(histories['LP'])+1)),    histories['LP']),
        ('ISOCP', list(range(1, len(histories['ISOCP'])+1)), histories['ISOCP']),
        out_path='otd_convergence.svg',log_scale=False
    )
