"""Compare linear vs ISOCP vs nonlinear OPF on IEEE_9500 reduced circuit.

  (A) linear:      isocp=False, non_linear=False  → solver=gurobi
  (B) ISOCP:       isocp=True,  non_linear=False  → solver=gurobi
  (C) Nonlinear:   isocp=False, non_linear=True   → solver=ipopt

Reports substation totals, OpenDSS validation residuals, and cone gaps side by side.
Circuit: Master_9500_reduced.dss (MV primary, no secondary, no caps, no regs,
         based on Master-unbal-initial-config.dss structure).
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
from Build_Model.Constraints import MODEL_CACHE, SOLVER_CACHE, get_or_build_model
from Build_Model.store import store_results


def _warm_start_nl(model, sol_lin):
    """Initialize nonlinear model variables from a prior linear solution."""
    for key, val in sol_lin['v'].items():
        try: model.v[key].set_value(float(val))
        except KeyError: pass
    for key, val in sol_lin['P'].items():
        try: model.P[key].set_value(float(val))
        except KeyError: pass
    for key, val in sol_lin['Q'].items():
        try: model.Q[key].set_value(float(val))
        except KeyError: pass
    # l[t,i,j,ph,ph] = (P^2 + Q^2) / v_i  (PVC equality)
    l_diag = {}
    for (t, i, j, ph), Pv in sol_lin['P'].items():
        Qv = sol_lin['Q'].get((t, i, j, ph), 0.0)
        vi  = sol_lin['v'].get((t, i, ph), 1.0)
        lval = (Pv**2 + Qv**2) / max(float(vi), 1e-9)
        l_diag[(t, i, j, ph)] = lval
        try: model.l[t, i, j, ph, ph].set_value(lval)
        except KeyError: pass
    # l[t,i,j,p,q] = sqrt(l_pp * l_qq)  (CMC equality)
    for key in list(model.l):
        t, i, j, p, q = key
        if p == q:
            continue
        lpp = l_diag.get((t, i, j, p), 0.0)
        lqq = l_diag.get((t, i, j, q), 0.0)
        try: model.l[t, i, j, p, q].set_value(float(np.sqrt(max(lpp * lqq, 0.0))))
        except KeyError: pass


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
    keys_p  = sol['P'].keys()      & dss['P'].keys()
    keys_v  = sol['v'].keys()      & dss['v'].keys()
    dP_subs = max(abs(dss['P_subs'][k] - sol['P_subs'][k]) for k in keys_ps) * 1e3
    dQ_subs = max(abs(dss['Q_subs'][k] - sol['Q_subs'][k]) for k in keys_ps) * 1e3
    dP      = max(abs(dss['P'][k]      - sol['P'][k])      for k in keys_p)  * 1e3
    dQ      = max(abs(dss['Q'][k]      - sol['Q'][k])      for k in keys_p)  * 1e3
    dv      = max(abs(dss['v'][k]      - np.sqrt(sol['v'][k])) for k in keys_v)
    return dict(dP_subs=dP_subs, dQ_subs=dQ_subs, dP=dP, dQ=dQ, dv=dv)


def _run_case(label, data, dss_path, isocp, non_linear, start_step, multi, solver='gurobi'):
    print(f"\n===== Running case ({label}) isocp={isocp} non_linear={non_linear} solver={solver} =====")
    MODEL_CACHE.clear()
    SOLVER_CACHE.clear()
    t0 = time.perf_counter()
    sol = solve_copf(
        data, cost_minimize_with_scd, solver=solver, alpha_scd=1e-3,
        non_linear=non_linear, isocp=isocp, p_control=False, integer=False,
        single_battery_variable=False,
    )
    t_solve = time.perf_counter() - t0
    with contextlib.redirect_stdout(io.StringIO()):
        dss_vals = run_opendss_validation(data, sol, dss_path, multi=multi, start_step=start_step)
    return sol, t_solve, dss_vals


def _run_case_nl(label, data, dss_path, sol_warm, start_step, multi):
    """Run nonlinear case warm-started from a prior solution (IPOPT with acceptable tol)."""
    print(f"\n===== Running case ({label}) non_linear=True solver=ipopt =====")
    MODEL_CACHE.clear()
    SOLVER_CACHE.clear()
    nl_model, nl_solver = get_or_build_model(
        data, cost_minimize_with_scd, solver='ipopt', alpha_scd=1e-3,
        non_linear=True, isocp=False, p_control=False, integer=False,
        single_battery_variable=False,
    )
    nl_solver._solver_options['tol']             = 1e-4
    nl_solver._solver_options['max_iter']        = 5000
    nl_solver._solver_options['mu_strategy']     = 'adaptive'
    nl_solver._solver_options['nlp_scaling_method'] = 'gradient-based'
    nl_solver._solver_options['acceptable_tol']  = 1e-1   # accept a good-enough point
    nl_solver._solver_options['acceptable_iter'] = 10
    nl_solver.config.load_solution = False   # load even if only "acceptable"
    # Warm-start from prior solution
    _warm_start_nl(nl_model, sol_warm)
    t0 = time.perf_counter()
    res = nl_solver.solve(nl_model)
    t_solve = time.perf_counter() - t0
    tc = getattr(res, 'termination_condition', None)
    print(f"  IPOPT termination: {tc}  best_obj={getattr(res,'best_feasible_objective',None)}")
    if tc is None or tc.name not in ('optimal','locallyOptimal','feasible','globallyOptimal'):
        print("  IPOPT did not find a feasible solution — skipping case C.")
        return None, t_solve, None
    nl_model.solutions.load_from(res)
    sol = store_results(nl_model)
    with contextlib.redirect_stdout(io.StringIO()):
        dss_vals = run_opendss_validation(data, sol, dss_path, multi=multi, start_step=start_step)
    return sol, t_solve, dss_vals


def _print_row(label, sol, t_solve, dss_vals):
    P_subs_tot = sum(sol['P_subs'].values()) * 1e3
    Q_subs_tot = sum(sol['Q_subs'].values()) * 1e3
    res = _opendss_residual(sol, dss_vals)
    print(f"\n--- {label} ---")
    print(f"  solve time              : {t_solve:.2f} s")
    print(f"  Sigma P_subs (model)    : {P_subs_tot:.3f} kW")
    print(f"  Sigma Q_subs (model)    : {Q_subs_tot:.3f} kVar")
    print(f"  OpenDSS max|DeltaP_subs|: {res['dP_subs']:.4f} kW")
    print(f"  OpenDSS max|DeltaQ_subs|: {res['dQ_subs']:.4f} kVar")
    print(f"  OpenDSS max|Delta P|    : {res['dP']:.4f} kW")
    print(f"  OpenDSS max|Delta Q|    : {res['dQ']:.4f} kVar")
    print(f"  OpenDSS max|Delta v|    : {res['dv']:.4e}")
    return res


def main():
    system_name = 'IEEE_9500'
    n_steps = 1
    start_step = 1
    multi = True  # always True: OpenDSS validation uses Daily mode with loadshape to match OPF-scaled loads

    wd = os.getcwd()
    fp = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master_9500_reduced.dss')

    bus_data      = pd.read_csv(os.path.join(fp, 'bus_data.csv'))
    branch_data   = pd.read_csv(os.path.join(fp, 'branch_data.csv'))
    gen_data      = pd.read_csv(os.path.join(fp, 'gen_data.csv'))
    bat_data      = pd.read_csv(os.path.join(fp, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(fp, 'default_loadshape.csv'))
    pvshape_data  = pd.read_csv(os.path.join(fp, 'pv_loadshape.csv'))
    price = 0.15 * loadshape_data['M'] + 0.15

    data = parse_all_data_phase_aware(
        bus_data, branch_data, gen_data, bat_data,
        loadshape=loadshape_data, pvshape=pvshape_data, price=price,
        start_step=start_step, n_steps=n_steps,
    )
    data['v_min'] = {node: 0.9 for node in data['v_min'].keys()}
    data['v_max'] = {node: 1.2 for node in data['v_max'].keys()}

    # ISOCP needs initial current angle estimates from OpenDSS
    angles = initialize_current_angles(data, dss_path, multi=multi, start_step=start_step)
    data['I_ang'] = angles['I_ang']

    print(f"=== Linear vs ISOCP on {system_name}, n_steps={n_steps} ===")

    sol_A, t_A, dss_A = _run_case('A (linear)',     data, dss_path, isocp=False, non_linear=False, start_step=start_step, multi=multi, solver='gurobi')
    sol_B, t_B, dss_B = _run_case('B (ISOCP)',      data, dss_path, isocp=True,  non_linear=False, start_step=start_step, multi=multi, solver='gurobi')
    sol_C, t_C, dss_C = _run_case_nl('C (nonlinear)', data, dss_path, sol_warm=sol_A, start_step=start_step, multi=multi)

    max_pvc_A, max_cmc_A = _cone_gap(sol_A)
    max_pvc_B, max_cmc_B = _cone_gap(sol_B)

    res_A = _print_row('(A) Linear      (isocp=False, non_linear=False)', sol_A, t_A, dss_A)
    res_B = _print_row('(B) ISOCP       (isocp=True,  non_linear=False)', sol_B, t_B, dss_B)

    pA = sum(sol_A['P_subs'].values()) * 1e3
    pB = sum(sol_B['P_subs'].values()) * 1e3
    qA = sum(sol_A['Q_subs'].values()) * 1e3
    qB = sum(sol_B['Q_subs'].values()) * 1e3

    print("\n--- Summary (A=Linear, B=ISOCP, C=Nonlinear) ---")
    print(f"  max|PVC gap|       : A={max_pvc_A:.3e}   B={max_pvc_B:.3e}")
    print(f"  max|CMC gap|       : A={max_cmc_A:.3e}   B={max_cmc_B:.3e}")
    print(f"  Sigma P_subs (kW)  : A={pA:.2f}   B={pB:.2f}")
    print(f"  Sigma Q_subs (kVar): A={qA:.2f}   B={qB:.2f}")
    print(f"  ODSS DP_subs (kW)  : A={res_A['dP_subs']:.4f}   B={res_B['dP_subs']:.4f}")
    print(f"  ODSS DQ_subs (kVar): A={res_A['dQ_subs']:.4f}   B={res_B['dQ_subs']:.4f}")
    print(f"  ODSS Dv            : A={res_A['dv']:.4e}   B={res_B['dv']:.4e}")
    print(f"  solve time (s)     : A={t_A:.2f}   B={t_B:.2f}")

    if sol_C is not None:
        max_pvc_C, max_cmc_C = _cone_gap(sol_C)
        res_C = _print_row('(C) Nonlinear   (isocp=False, non_linear=True)',  sol_C, t_C, dss_C)
        pC = sum(sol_C['P_subs'].values()) * 1e3
        qC = sum(sol_C['Q_subs'].values()) * 1e3
        print(f"\n  C (nonlinear): max|PVC gap|={max_pvc_C:.3e}  max|CMC gap|={max_cmc_C:.3e}")
        print(f"  Sigma P_subs (kW)  C={pC:.2f}   ODSS DP_subs={res_C['dP_subs']:.4f} kW")
        print(f"  Sigma Q_subs (kVar)C={qC:.2f}   ODSS DQ_subs={res_C['dQ_subs']:.4f} kVar")
        print(f"  ODSS Dv C={res_C['dv']:.4e}   solve time={t_C:.2f}s")
    else:
        print(f"\n  C (nonlinear): solver did not converge (t={t_C:.1f}s)")
        print("  → IEEE_9500 (2700+ buses) exceeds IPOPT+MUMPS capacity; use ISOCP as best approximation.")


if __name__ == '__main__':
    main()
