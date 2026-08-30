"""Standalone driver: run DDDP+ISOCP on IEEE 123-bus, T=24, gurobi.
Mirrors the configuration used by the OTD benchmarks so timings/objectives
are directly comparable.
"""
import os
import time

# Gurobi WLS SSL fix (mirrors OTD_parallel.py / main.py): NREL corporate
# proxy uses a self-signed root CA that Gurobi's bundled OpenSSL can't
# verify. Point GRB_CAFILE at the extracted CA bundle if present.
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

import pandas as pd

from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from OpenDss.OpenDssValidate import initialize_current_angles
from Decomposition.Temporal.dddp_isocp import dddp_solve


def main():
    system_name = 'IEEE_123'
    wd = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')

    bus_data = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price = 0.15 * loadshape_data['M'] + 0.15

    obj = cost_minimize_with_scd
    multi = True
    non_linear = False
    isocp = True
    p_control = False
    integer = False
    single_battery_variable = False
    solver = 'gurobi'
    alpha_scd = 1e-2
    n_steps = 24
    start_step = 1

    data = parse_all_data_phase_aware(
        bus_data, branch_data, gen_data, bat_data,
        loadshape=loadshape_data, pvshape=pvshape_data,
        price=price, start_step=start_step, n_steps=n_steps,
    )
    data['v_min'] = {k: 0.9 for k in data['v_min']}
    data['v_max'] = {k: 1.2 for k in data['v_max']}

    if non_linear or isocp:
        angles = initialize_current_angles(data, dss_path, multi=multi, start_step=start_step)
        data['I_ang'] = angles['I_ang']

    print(f"\nDDDP+ISOCP | {system_name} | T={n_steps} | solver={solver} | isocp={isocp}\n")
    t0 = time.perf_counter()
    LB, cuts, LB_hist, UB_hist = dddp_solve(
        data, obj,
        solver=solver, alpha_scd=alpha_scd,
        max_iters=50, tol=1e-3,
        non_linear=non_linear, isocp=isocp,
        p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
    )
    elapsed = time.perf_counter() - t0

    print(f"\n{'='*55}")
    print(f"  Solver       : {solver} | isocp={isocp}")
    print(f"  DDDP total   : {elapsed:.2f}s")
    print(f"  Iterations   : {len(LB_hist)}")
    print(f"  Final LB     : {LB_hist[-1]:.6f}")
    print(f"  Final UB     : {UB_hist[-1]:.6f}")
    print(f"  LB-UB gap    : {abs(UB_hist[-1]-LB_hist[-1])/abs(LB_hist[-1])*100:.4f}%")
    print(f"{'='*55}")


if __name__ == '__main__':
    main()
