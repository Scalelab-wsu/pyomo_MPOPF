import os

from sympy import true

from Plot.Plotting import plot_network
# Gurobi WLS SSL fix: NREL corporate proxy uses a self-signed root CA that
# Gurobi's bundled OpenSSL can't verify. Point GRB_CAFILE at the extracted
# NREL cert chain so the WLS license token request succeeds.
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

# Make IDAES-installed ipopt visible to pyomo's appsi.Ipopt
_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if os.path.isdir(_idaes_bin) and _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

# # appsi.Ipopt only treats "Optimal Solution Found" as optimal; ipopt on this
# # non-convex BFM frequently exits "Solved To Acceptable Level" (primal feasible
# # to ~1e-11, only the dual is loose). Patch the parser to accept that.
# from pyomo.contrib.appsi.solvers import ipopt as _appsi_ipopt
# _orig_parse_sol = _appsi_ipopt.Ipopt._parse_sol
# def _patched_parse_sol(self):
#     with open(self._filename + '.sol', 'r') as _f:
#         _content = _f.read()
#     if 'Optimal Solution Found' not in _content and 'Solved To Acceptable Level' in _content:
#         _content = _content.replace('Solved To Acceptable Level',
#                                     'Optimal Solution Found', 1)
#         with open(self._filename + '.sol', 'w') as _f:
#             _f.write(_content)
#     return _orig_parse_sol(self)
# _appsi_ipopt.Ipopt._parse_sol = _patched_parse_sol

from Plot.Plotting import *
# from Plot.time_series_plot import *

from OpenDss.OpenDssValidate import run_opendss_validation,all_time_highest_discrepancy,initialize_current_angles
from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize, power_flow, cost_minimize_with_scd, \
    loss_minimize_with_scd
from Centralized.copf import solve_copf
# from Centralized.copf_fast import solve_copf
from Decomposition.Spatial.enapp import solve_EnAPP
from Decomposition.Spatial.admm import solve_ADMM
from Decomposition.Spatial.area_information import *
from Decomposition.Spatial.separate_areas import  split_data_into_areas
# from Decomposition.Temporal.DDDP_M_cache import *
from Decomposition.Temporal.DDDP_Persistent import *
import pandas as pd
from Helpers import *
                                    
# system_name = 'IEEE_13'
system_name = 'IEEE_123'
# system_name = 'IEEE_9500'
# area_info = eval(f'{system_name}' + '_area_info')
# obj = loss_minimize_with_scd
obj = cost_minimize_with_scd
# obj = voltage_deviation_minimize
# obj = power_flow
wd = os.path.dirname(os.path.abspath(__file__))
filepath = os.path.join(wd, "rawData", system_name,"csvs")
dss_path = os.path.join(wd, "rawData", system_name,"dss_scripts","Master.dss")
bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
## chaning 2h battery to 4h battery for testing purposes
# for col in ['bmin_a', 'bmin_b', 'bmin_c', 'bmax_a', 'bmax_b', 'bmax_c']:
#     if col in bat_data.columns:
#         bat_data[col] *= 2
# plot_network(bus_data,branch_data,gen_data,bat_data)
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
price = 0.15* loadshape_data['M'] + 0.15

# %%
if __name__ == "__main__":

    centralized = True
    ADMM = False
    enAPP = False
    DDDP = False
    opendss = True
    multi = True
    non_linear = True
    isocp = False
    p_control = False
    integer = False
    single_battery_variable = False
    start_step = 1
    n_steps = 24
    solver = 'ipopt' if non_linear else 'gurobi'
    alpha_scd=1e-3

    data_single = parse_all_data_phase_aware(bus_data, branch_data,n_steps=1) ## for 24 hrs default n_steps is 24 hrs
    data = parse_all_data_phase_aware(bus_data, branch_data,gen_data,bat_data,loadshape=loadshape_data,pvshape=pvshape_data,price=price,start_step=start_step,n_steps=n_steps) ## why using loadshape=None in full model gives better results?
    data['v_min'] = { node: 0.9 for node in data['v_min'].keys() }
    data['v_max'] = { node: 1.2 for node in data['v_max'].keys() }
    if multi:
        data = data
    else:
        data = data_single

    if non_linear or isocp:
        angles = initialize_current_angles(data, dss_path, multi=multi, start_step=start_step)
        data['I_ang'] = angles['I_ang']

    if centralized:
        print(f"Solving centralized problem for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        copfVals = solve_copf(data, obj, solver=solver,alpha_scd=alpha_scd,non_linear=non_linear,isocp=isocp, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
        end_time = time.time()  # End timing
        centralized_time = end_time - start_time

        # Print results
        print(f"Total substation Real Power Flows: {sum(copfVals['P_subs'].values())* 1e3} kW")
        print(f"Total substation Reactive Power Flows: {sum(copfVals['Q_subs'].values())* 1e3} kVar")
        print(f"total load KW : {sum(data['p_L'].values()) * 1e3}")
        print(f"total load Kvar : {sum(data['q_L'].values()) * 1e3}")
        print(f"total PV KW : {sum(data['p_D'].values())*1e3}")
        print(f"Total reactive power from PV Kvar: {sum(copfVals['q_D'].values())*1e3}")
        # Battery printing - handle both linear and non-linear models
        if 'P_b' in copfVals:
            print(f"Total battery power kW (P_b): {sum(copfVals['P_b'].values())}")
            print(f"Total battery Charging Power kW (P_c):{sum(v for v in copfVals['P_b'].values() if v > 0)*1e3}")
            print(f"Total battery disCharging Power kW (P_d): {sum(-v for v in copfVals['P_b'].values() if v < 0)*1e3}")
        elif 'P_c' in copfVals and 'P_d' in copfVals:
            check_simultaneous_charging_discharging(copfVals)
            print(f"Total battery Charging Power kW (P_c): {sum(copfVals['P_c'].values())*1e3}")
            print(f"Total battery disCharging Power kW (P_d): {sum(copfVals['P_d'].values())*1e3}")
            print(f"Total battery net real power kW: {(sum(copfVals['P_d'].values()) - sum(copfVals['P_c'].values()))*1e3}")

        print(f"Centralized Objective Value: {copfVals['objective_value']}")
        print(f"Centralized Solver Time: {centralized_time:.2f} seconds")
        print()

        # ---- OPF losses via energy balance (everything in kW / kVAr) ----
        # All copfVals quantities are stored in MW / MVAr (per-unit on a 1 MVA
        # base × pu_to_kw=1), so multiply by 1e3 to convert to kW / kVAr.
        p_subs_kw = sum(copfVals['P_subs'].values()) * 1e3
        q_subs_kvar = sum(copfVals['Q_subs'].values()) * 1e3
        p_load_kw = sum(data['p_L'].values()) * 1e3
        q_load_kvar = sum(data['q_L'].values()) * 1e3
        p_pv_kw = sum(copfVals['p_D'].values()) * 1e3
        q_pv_kvar = sum(copfVals['q_D'].values()) * 1e3
        if 'P_c' in copfVals and 'P_d' in copfVals:
            bat_inject_kw = (sum(copfVals['P_d'].values()) - sum(copfVals['P_c'].values())) * 1e3
        elif 'P_b' in copfVals:
            # P_b > 0  ⇒ charging (consumption); injection sign is -P_b
            bat_inject_kw = -sum(copfVals['P_b'].values()) * 1e3
        else:
            bat_inject_kw = 0.0

        opf_p_loss_kw = p_subs_kw + p_pv_kw + bat_inject_kw - p_load_kw
        opf_q_loss_kvar = q_subs_kvar + q_pv_kvar - q_load_kvar
        print("===== OPF aggregate results (kW / kVAr) =====")
        print(f"  Substation real power      : {p_subs_kw:>12.2f} kW")
        print(f"  Substation reactive power  : {q_subs_kvar:>12.2f} kVAr")
        print(f"  Load                       : {p_load_kw:>12.2f} kW  | {q_load_kvar:>12.2f} kVAr")
        print(f"  PV output                  : {p_pv_kw:>12.2f} kW  | {q_pv_kvar:>12.2f} kVAr")
        print(f"  Battery net (injection +)  : {bat_inject_kw:>12.2f} kW")
        print(f"  Total active loss (P_subs + PV + bat_inj - load) : {opf_p_loss_kw:>10.2f} kW")
        print(f"  Total reactive loss (Q_subs + Q_PV - Q_load)     : {opf_q_loss_kvar:>10.2f} kVAr")
        print("=============================================")
        print()

        # if isocp and copfVals.get('isocp_gap_history'):
        #     plot_isocp_convergence(
        #         (system_name, copfVals['isocp_gap_history']),
        #         out_path='isocp_convergence.svg',log_scale=False,
        #     )

    if ADMM:
        data_area = split_data_into_areas(data, area_info)
        print(f"Solving ADMM for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        admmVals,admm_obj,admm_aug_obj,admm_conv = solve_ADMM(data, data_area, area_info, obj, solver=solver,alpha_scd=alpha_scd,rho=1e-2, max_iterations=500,non_linear=non_linear,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
        end_time = time.time()  # End timing
        admm_time = end_time - start_time
        print(f"Total substation Real Power Flows: {sum(admmVals['P_subs'].values())}")
        print(f"Total substation Reactive Power Flows: {sum(admmVals['Q_subs'].values())}")
        print(f"Total reactive power from PV : {sum(admmVals['q_D'].values())}")
        print(f"Total battery Charging Power : {sum(admmVals['P_c'].values())}")
        print(f"Total battery disCharging Power : {sum(admmVals['P_d'].values())}")
        print("ADMM ran successfully")
        print(f"ADMM Solver Time: {admm_time:.2f} seconds")

    if enAPP:
        data_area = split_data_into_areas(data, area_info)
        print(f"Solving EnAPP for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        enappVals,enapp_obj,enapp_conv = solve_EnAPP(data,data_area,area_info,obj, solver=solver,alpha_scd=alpha_scd,max_iterations=50,alpha=0,non_linear=non_linear,isocp=isocp,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
        end_time = time.time()  # End timing
        enapp_time = end_time - start_time
        print(f"Total substation Real Power Flows: {sum(enappVals['P_subs'].values())}")
        print(f"Total substation Reactive Power Flows: {sum(enappVals['Q_subs'].values())}")
        print(f"Total reactive power from PV : {sum(enappVals['q_D'].values())}")
        print(f"Total battery Charging Power : {sum(enappVals['P_c'].values())}")
        print(f"Total battery disCharging Power : {sum(enappVals['P_d'].values())}")
        print("EnAPP ran successfully")
        print(f"EnAPP Solver Time: {enapp_time:.2f} seconds")

    if DDDP:
        # print(f"Solving DDDP for {system_name} and objective function {obj}...")
        # start_time = time.time()  # Start timing
        # LB, cuts,LB_container,UB_container = dddp_solve(data, obj,solver=solver,alpha_scd=alpha_scd,max_iters=50,tol = 1e-3,non_linear=non_linear,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
        # # dddpVals = collect_converged_solution(data, cuts, obj, solver=solver,alpha_scd=alpha_scd,non_linear=non_linear, p_control=p_control, integer=integer)
        # end_time = time.time()
        # dddp_time = end_time - start_time
        # print(f"DDDP ran successfully")
        # print(f"DDDP Solver Time: {dddp_time:.2f} seconds")

        from Decomposition.Temporal.dddp_isocp import dddp_solve
        start_time = time.time()  # Start timing
        LB, cuts, LB_hist, UB_hist = dddp_solve(data, obj,solver=solver,alpha_scd=alpha_scd,max_iters=50,tol = 1e-3,non_linear=non_linear,isocp=isocp,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
        # dddpVals = collect_converged_solution(data, cuts, obj, solver=solver, alpha_scd=alpha_scd,non_linear=non_linear, p_control=p_control, integer=integer)
        end_time = time.time()
        dddp_time = end_time - start_time
        print(f"DDDP ran successfully")
        print(f"DDDP Solver Time: {dddp_time:.2f} seconds")

    if opendss:
        dssVals = run_opendss_validation(data, copfVals, dss_path, multi = multi,start_step=start_step)
        all_time_highest_discrepancy(dssVals,copfVals)  ## calculates maximum differences between solutions. first argument should hold keys we want to comapre.

        # ---- Side-by-side OPF vs OpenDSS comparison (kW / kVAr) ----
        if centralized and 'totals_kw' in dssVals:
            tk = dssVals['totals_kw']
            print()
            print("===== OPF  vs  OpenDSS (kW / kVAr) =====")
            print(f"  {'quantity':<28} {'OPF':>14}   {'OpenDSS':>14}   {'gap':>12}")
            rows = [
                ('P_subs (kW)',         p_subs_kw,       tk['P_subs']),
                ('Q_subs (kVAr)',       q_subs_kvar,     tk['Q_subs']),
                ('Load (kW)',           p_load_kw,       tk['p_load_circuit']),
                ('Load (kVAr)',         q_load_kvar,     tk['q_load_circuit']),
                ('PV (kW)',             p_pv_kw,         tk['p_PV']),
                ('PV (kVAr)',           q_pv_kvar,       tk['q_PV']),
                ('Battery net (kW)',    bat_inject_kw,   tk['bat_net_kW']),
                ('Active loss (kW)',    opf_p_loss_kw,   tk['P_loss']),
                ('Reactive loss (kVAr)',opf_q_loss_kvar, tk['Q_loss']),
            ]
            for name, opf_v, dss_v in rows:
                print(f"  {name:<28} {opf_v:>14.2f}   {dss_v:>14.2f}   {opf_v-dss_v:>12.2f}")
            print("========================================")
        print()

    # plot_battery_soc(copfVals=copfVals)
    # # plot_convergence_comparison(copfVals=copfVals,dddpVals=dddpVals,enappVals=enappVals)
    # conv_args = {}
    # if centralized:
    #     conv_args["copfVals"] = {"objective_value": copfVals["objective_value"]}
    # if DDDP:
    #     conv_args["dddpVals"] = {"LB": LB_container, "UB": UB_container}
    # if enAPP:
    #     conv_args["enappVals"] = {"values": list(enapp_obj.values()) if isinstance(enapp_obj, dict) else enapp_obj}
    # if ADMM:
    #     conv_args["admmVals"] = {"values": list(admm_obj.values()) if isinstance(admm_obj, dict) else admm_obj}
    #
    # plot_convergence_comparison(**conv_args)

    # # plot_voltage(copfvals=copfVals,dssVals=dssVals)
    # plot_substation_power(copfvals=copfVals,dssVals=dssVals)
    # plot_active_power_flows(copfvals=copfVals,dssVals=dssVals)
    # plot_reactive_power_flows(copfvals=copfVals,dssVals=dssVals)

