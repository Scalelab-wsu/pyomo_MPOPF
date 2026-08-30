"""Compare two OPF runs:
  (A) isocp=True, max_inner=0   -> initial SOCP relaxation only
  (B) isocp=True, max_inner=30  -> full convex-iteration SOCP (AC-exact)

Reports cone gap, substation totals, and OpenDSS validation residual
side by side.
"""

import os
import io
import time
import contextlib
import numpy as np
import pandas as pd

_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

from OpenDss.OpenDssValidate import run_opendss_validation, initialize_current_angles
from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from Centralized.copf import solve_copf
from Build_Model.Constraints import MODEL_CACHE, SOLVER_CACHE


def _cone_gap(sol):
    P, Q, v, l = sol['P'], sol['Q'], sol['v'], sol['l']
    max_pvc = 0.0
    for (t, i, j, ph), Pv in P.items():
        Qv = Q[t, i, j, ph]
        vv = v[t, i, ph]
        lpp = l[t, i, j, ph, ph]
        g = Pv * Pv + Qv * Qv - vv * lpp
        if abs(g) > max_pvc:
            max_pvc = abs(g)
    max_cmc = 0.0
    for (t, i, j, p, q), lpq in l.items():
        if p == q:
            continue
        lpp = l[t, i, j, p, p]
        lqq = l[t, i, j, q, q]
        g = lpq * lpq - lpp * lqq
        if abs(g) > max_cmc:
            max_cmc = abs(g)
    return max_pvc, max_cmc


def _opendss_residual(sol, dss):
    keys_ps = sol['P_subs'].keys() & dss['P_subs'].keys()
    keys_p = sol['P'].keys() & dss['P'].keys()
    keys_v = sol['v'].keys() & dss['v'].keys()
    dP_subs = max(abs(dss['P_subs'][k] - sol['P_subs'][k]) for k in keys_ps) * 1e3
    dQ_subs = max(abs(dss['Q_subs'][k] - sol['Q_subs'][k]) for k in keys_ps) * 1e3
    dP = max(abs(dss['P'][k] - sol['P'][k]) for k in keys_p) * 1e3
    dQ = max(abs(dss['Q'][k] - sol['Q'][k]) for k in keys_p) * 1e3
    dv = max(abs(dss['v'][k] - np.sqrt(sol['v'][k])) for k in keys_v)
    return dict(dP_subs=dP_subs, dQ_subs=dQ_subs, dP=dP, dQ=dQ, dv=dv)


def _run_case(label, data, dss_path, max_inner):
    print(f"\n===== Running case ({label}) max_inner={max_inner} =====")
    MODEL_CACHE.clear()
    SOLVER_CACHE.clear()
    t0 = time.perf_counter()
    sol = solve_copf(
        data, cost_minimize_with_scd, solver='gurobi', alpha_scd=1e-3,
        non_linear=False, isocp=True, p_control=False, integer=False,
        single_battery_variable=False,
        gamma=0.5, inner_tol=1e-4, gap_tol=1e-4, max_inner=max_inner,
    )
    t_solve = time.perf_counter() - t0
    with contextlib.redirect_stdout(io.StringIO()):
        dss_vals = run_opendss_validation(data, sol, dss_path, multi=True, start_step=1)
    return sol, t_solve, dss_vals


def _print_row(label, sol, t_solve, dss_vals, max_pvc, max_cmc):
    P_subs_tot = sum(sol['P_subs'].values()) * 1e3
    Q_subs_tot = sum(sol['Q_subs'].values()) * 1e3
    res = _opendss_residual(sol, dss_vals)
    print(f"\n--- {label} ---")
    print(f"  solve time              : {t_solve:.2f} s")
    print(f"  max|cone PVC gap|       : {max_pvc:.3e}")
    print(f"  max|cone CMC gap|       : {max_cmc:.3e}")
    print(f"  Sigma P_subs (model)    : {P_subs_tot:.3f} kW")
    print(f"  Sigma Q_subs (model)    : {Q_subs_tot:.3f} kVar")
    print(f"  OpenDSS max|DeltaP_subs|: {res['dP_subs']:.4f} kW")
    print(f"  OpenDSS max|DeltaQ_subs|: {res['dQ_subs']:.4f} kVar")
    print(f"  OpenDSS max|Delta P|    : {res['dP']:.4f} kW")
    print(f"  OpenDSS max|Delta Q|    : {res['dQ']:.4f} kVar")
    print(f"  OpenDSS max|Delta v|    : {res['dv']:.4e}")
    return res


def main():
    system_name = 'IEEE_123_other'
    wd = os.getcwd()
    fp = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')
    bus_data = pd.read_csv(os.path.join(fp, 'bus_data.csv'))
    branch_data = pd.read_csv(os.path.join(fp, 'branch_data.csv'))
    gen_data = pd.read_csv(os.path.join(fp, 'gen_data.csv'))
    bat_data = pd.read_csv(os.path.join(fp, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(fp, 'default_loadshape.csv'))
    pvshape_data = pd.read_csv(os.path.join(fp, 'pv_loadshape.csv'))
    price = 0.15 * loadshape_data['M'] + 0.15

    n_steps = 24
    data = parse_all_data_phase_aware(
        bus_data, branch_data, gen_data, bat_data,
        loadshape=loadshape_data, pvshape=pvshape_data, price=price,
        start_step=1, n_steps=n_steps,
    )
    data['v_min'] = {node: 0.9 for node in data['v_min'].keys()}
    data['v_max'] = {node: 1.2 for node in data['v_max'].keys()}
    angles = initialize_current_angles(data, dss_path, multi=True, start_step=1)
    data['I_ang'] = angles['I_ang']

    print(f"=== ISOCP comparison on {system_name}, n_steps={n_steps} ===")

    sol_A, t_A, dss_A = _run_case('A', data, dss_path, max_inner=0)
    max_pvc_A, max_cmc_A = _cone_gap(sol_A)

    sol_B, t_B, dss_B = _run_case('B', data, dss_path, max_inner=30)
    max_pvc_B, max_cmc_B = _cone_gap(sol_B)

    res_A = _print_row('(A) SOCP relaxation only (max_inner=0)', sol_A, t_A, dss_A, max_pvc_A, max_cmc_A)
    res_B = _print_row('(B) ISOCP iteration       (max_inner=30)', sol_B, t_B, dss_B, max_pvc_B, max_cmc_B)

    pA = sum(sol_A['P_subs'].values()) * 1e3
    pB = sum(sol_B['P_subs'].values()) * 1e3
    qA = sum(sol_A['Q_subs'].values()) * 1e3
    qB = sum(sol_B['Q_subs'].values()) * 1e3

    print("\n--- B vs A ---")
    print(f"  max|PVC gap|       : A={max_pvc_A:.3e}   B={max_pvc_B:.3e}   "
          f"ratio={(max_pvc_B/max_pvc_A) if max_pvc_A else 0:.2e}")
    print(f"  max|CMC gap|       : A={max_cmc_A:.3e}   B={max_cmc_B:.3e}   "
          f"ratio={(max_cmc_B/max_cmc_A) if max_cmc_A else 0:.2e}")
    print(f"  Sigma P_subs (kW)  : A={pA:.2f}   B={pB:.2f}   Delta={pB-pA:+.2f}")
    print(f"  Sigma Q_subs (kVar): A={qA:.2f}   B={qB:.2f}   Delta={qB-qA:+.2f}")
    print(f"  ODSS DP_subs (kW)  : A={res_A['dP_subs']:.4f}   B={res_B['dP_subs']:.4f}   "
          f"Delta={res_B['dP_subs']-res_A['dP_subs']:+.4f}")
    print(f"  ODSS DQ_subs (kVar): A={res_A['dQ_subs']:.4f}   B={res_B['dQ_subs']:.4f}   "
          f"Delta={res_B['dQ_subs']-res_A['dQ_subs']:+.4f}")
    print(f"  ODSS Dv            : A={res_A['dv']:.4e}   B={res_B['dv']:.4e}   "
          f"Delta={res_B['dv']-res_A['dv']:+.4e}")
    print(f"  solve time (s)     : A={t_A:.2f}   B={t_B:.2f}   Delta={t_B-t_A:+.2f}")


if __name__ == '__main__':
    main()
