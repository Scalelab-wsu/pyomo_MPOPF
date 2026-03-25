# from Plotter import *
# from Plotter_extras import *
from OpenDss.OpenDssValidate import run_opendss_validation,all_time_highest_discrepancy,initialize_current_angles
from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize, power_flow, cost_minimize_with_scd
from Centralized.copf import solve_copf
from Decomposition.Spatial.enapp import solve_EnAPP
from Decomposition.Spatial.admm import solve_ADMM
from Decomposition.Spatial.area_information import *
from Decomposition.Spatial.separate_areas import  split_data_into_areas
from Decomposition.Temporal.DDDP_M_cache import *
# from Decomposition.Temporal.DDDP_Persistent import *
import pandas as pd
from Helpers import *

system_name = 'IEEE_123_other'
# system_name = 'IEEE_9500'
area_info = eval(f'{system_name}' + '_area_info')
obj = loss_minimize
# obj = cost_minimize_with_scd
# obj = voltage_deviation_minimize
# obj = power_flow
wd = os.getcwd()
filepath = os.path.join(wd, "rawData", system_name,"csvs")
dss_path = os.path.join(wd, "rawData", system_name,"dss_scripts","Master.dss")
bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
# plot_network(bus_data,branch_data)
gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
price = 0.15* loadshape_data['M'] + 0.15

data_single = parse_all_data_phase_aware(bus_data, branch_data,n_steps=1) ## for 24 hrs default n_steps is is 24 hrs
data = parse_all_data_phase_aware(bus_data, branch_data,gen_data,bat_data,loadshape=loadshape_data,pvshape=pvshape_data,price=price,start_step=1,n_steps=24) ## why using loadshape=None in full model gives better results?
# data['v_min'] = { node: 0.5 for node in data['v_min'].keys() }
# data['v_max'] = { node: 1.5 for node in data['v_max'].keys() }
# %%
if __name__ == "__main__":
    centralized = True
    ADMM = False
    enAPP = False
    DDDP = False
    opendss = True
    multi = True
    non_linear = False
    p_control = False
    integer = False
    solver = 'ipopt' if non_linear else 'gurobi'
    if multi:
        data = data
    else:
        data = data_single

    if non_linear:
        angles = initialize_current_angles(data, dss_path, multi=multi)
        data['I_ang'] = angles['I_ang']

    if centralized:
        print(f"Solving centralized problem for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        copfVals = solve_copf(data, obj, non_linear=non_linear, p_control=p_control, integer=integer)
        end_time = time.time()  # End timing
        centralized_time = end_time - start_time

        # Print results
        print(f"Total substation Real Power Flows: {sum(copfVals['P_subs'].values())} kW")
        print(f"Total substation Reactive Power Flows: {sum(copfVals['Q_subs'].values())} kVar")
        print(f"total load KW : {sum(data['p_L'].values()) * 1e3}")
        print(f"total load Kvar : {sum(data['q_L'].values()) * 1e3}")
        print(f"total PV KW : {sum(data['p_D'].values())*1e3}")
        print(f"Total reactive power from PV Kvar: {sum(copfVals['q_D'].values())}")
        # Battery printing - handle both linear and non-linear models
        if 'P_b' in copfVals:
            print(f"Total battery power kW (P_b): {sum(copfVals['P_b'].values())}")
        elif 'P_c' in copfVals and 'P_d' in copfVals:
            check_simultaneous_charging_discharging(copfVals)
            print(f"Total battery Charging Power kW (P_c): {sum(copfVals['P_c'].values())}")
            print(f"Total battery disCharging Power kW (P_d): {sum(copfVals['P_d'].values())}")
            print(f"Total battery net real power kW: {sum(copfVals['P_d'].values()) - sum(copfVals['P_c'].values())}")

        print(f"Centralized Objective Value: {copfVals['objective_value']}")
        print(f"Centralized Solver Time: {centralized_time:.2f} seconds")
        print()

    if ADMM:
        data_area = split_data_into_areas(data, area_info)
        print(f"Solving ADMM for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        admmVals,admm_obj,admm_aug_obj,admm_conv = solve_ADMM(data, data_area, area_info, obj, rho=5, max_iterations=500,non_linear=non_linear,p_control=p_control,integer=integer)
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
        enappVals,enapp_obj,enapp_conv = solve_EnAPP(data,data_area,area_info,obj, max_iterations=50,alpha=0,non_linear=non_linear,p_control=p_control,integer=integer)
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
        print(f"Solving DDDP for {system_name} and objective function {obj}...")
        start_time = time.time()  # Start timing
        LB, cuts,LB_container,UB_container = dddp_solve(data, obj, max_iters=50,tol = 1e-4,non_linear=non_linear,p_control=p_control,integer=integer)
        dddpVals = collect_converged_solution(data, cuts, obj, non_linear=non_linear, p_control=p_control, integer=integer)
        end_time = time.time()
        dddp_time = end_time - start_time
        print(f"DDDP ran successfully")
        print(f"DDDP Solver Time: {dddp_time:.2f} seconds")


    if opendss:
        dssVals = run_opendss_validation(data, copfVals, dss_path, multi = multi)
        print()

    all_time_highest_discrepancy(dssVals, copfVals)  ## calculates maximum differences between solutions. first argument should hold keys we want to comapre.

    # plot_voltage(copfvals=copfVals,dssVals=dssVals)
    # plot_active_power_flows(copfvals=copfVals,dssVals=dssVals)
    # plot_reactive_power_flows(copfvals=copfVals,dssVals=dssVals)
