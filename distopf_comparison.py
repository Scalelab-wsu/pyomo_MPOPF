# %%
import time
from Parser.parse_different import parse_all_data
from Build_Model.Constraints_new import build_pyomo_model
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize,power_flow,loss_minimize_with_scd,cost_minimize_with_scd
from Build_Model.store import store_results
from Distributed.separate_areas import split_data_into_areas
from Helpers import *
from Distributed.area_information import *
import pandas as pd
import os
from Distributed.admm_fast import solve_ADMM
from Distributed.enapp_fast import solve_EnAPP
from OpenDss.OpendssValidate_new import run_opendss_validation,all_time_highest_discrepancy
# from OpendssValidate import run_opendss_validation

import distopf as opf
import distopf.multiperiod as mpopf
from Plot.Plotting import *
system_name = 'IEEE_123_other'
area_info = eval(f'{system_name}' + '_area_info')
obj = loss_minimize_with_scd

wd = os.getcwd()
filepath = os.path.join(wd, "rawData", system_name,"csvs")

# Import CSV files
bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
# price = [
#     0.026, 0.025, 0.022, 0.02, 0.022, 0.024, 0.025, 0.026,
#     0.028, 0.034, 0.038, 0.035, 0.036, 0.037, 0.038, 0.04,
#     0.04, 0.03, 0.031, 0.029, 0.027, 0.025, 0.023, 0.026]
price = [
    0.027, 0.025, 0.023, 0.022, 0.022,
    0.026, 0.029, 0.030, 0.031, 0.031,
    0.035, 0.036, 0.033, 0.029, 0.032,
    0.032, 0.038, 0.040, 0.034, 0.037,
    0.027, 0.028, 0.025, 0.024
]
data = parse_all_data(bus_data, branch_data,gen=gen_data,bat=bat_data,loadshape=loadshape_data,pvshape=pvshape_data,price=price)
# data_area = split_data_into_areas(data, area_info)
# plot_network(bus_data,branch_data,gen_data,bat_data,data_area)
# data = parse_all_data(bus_data, branch_data,price=price,n_steps=1)
# from rawData.IEEE_123_other.dss_scripts.write_dss_scripts import create_opendss_scripts
# create_opendss_scripts(data)
# %%
if __name__ == "__main__":
    # print(f"Solving centralized problem for {system_name} and objective function {obj}...")
    # start_time = time.time()  # Start timing
    # centralized_model = build_pyomo_model(data)
    # centralized_model = pyomo_solve(centralized_model, obj)
    # copfVals = store_results(centralized_model)
    # end_time = time.time()  # End timing
    # centralized_time = end_time - start_time
    # check_simultaneous_charging_discharging(copfVals)
    # print(f"Total substation Real Power Flows: {sum(copfVals['P_subs'].values())}")
    # print(f"Total substation Reactive Power Flows: {sum(copfVals['Q_subs'].values())}")
    # print(f"Total reactive power from PV : {sum(copfVals['q_D'].values())}")
    # print(f"Total battery Charging Power : {sum(copfVals['P_c'].values())}")
    # print(f"Total battery disCharging Power : {sum(copfVals['P_d'].values())}")
    # print(f"Centralized Objective Value: {copfVals['objective_value']}")
    # print(f"Centralized Solver Time: {centralized_time:.2f} seconds")

    print(f"Solving with DistOPF for {system_name} and objective function {obj}...")
    start_time = time.time()   # Start timing
    dist_model = mpopf.LinDistModelMultiFast(
        bus_data=bus_data,
        branch_data=branch_data,
        gen_data=gen_data,
        bat_data=bat_data,
        pv_loadshape_data=pvshape_data,
        loadshape_data=loadshape_data,
        start_step=1,
        n_steps=24,
        delta_t=1,
    )
    result = mpopf.cvxpy_solve(dist_model, mpopf.cp_obj_loss_batt, solver="CLARABEL")
    end_time = time.time()  # End timing
    s = dist_model.get_apparent_power_flows(result.x)
    v = dist_model.get_voltages(result.x)
    p_gen = dist_model.get_p_gens(result.x)
    q_gen = dist_model.get_q_gens(result.x)
    p_charge = dist_model.get_p_charge(result.x)
    p_discharge = dist_model.get_p_discharge(result.x)
    obj_value = result.fun
    distopf_time = end_time - start_time
    # print(f"Total substation Real Power Flows: {sum(s.loc[1 ]}")
    # print(f"Total substation Reactive Power Flows: {sum(copfVals['Q_subs'].values())}")
    # print(f"Total reactive power from PV : {sum(copfVals['q_D'].values())}")
    # print(f"Total battery Charging Power : {sum(copfVals['P_c'].values())}")
    # print(f"Total battery disCharging Power : {sum(copfVals['P_d'].values())}")
    print(f"DistOPF Objective Value: {obj_value}")
    print(f"DistOPF Solver Time: {distopf_time:.2f} seconds")
    # %%
    # opendssVals = run_opendss_validation(data,enappVals)
    # # admm_opendssVals = run_opendss_validation(data, admmVals)
    # enapp_opendssVals = run_opendss_validation(data, enappVals)

    # all_time_highest_discrepancy(opendssVals,enappVals)
    plot_substation_power(copfVals=copfVals,enappVals=enappVals)
    plot_battery_soc(copfVals=copfVals,enappVals=enappVals)
    plot_reactive_power_flows(copfVals=copfVals,enappVals=enappVals)
    plot_der_reactive_power(copfVals=copfVals,enappVals=enappVals)
    plot_battery_charging_discharging_combined(copfVals=copfVals,enappVals=enappVals)
    plot_active_power_flows(copfVals=copfVals,enappVals=enappVals)
    plot_voltage(copfVals = copfVals,enappVals=enappVals)
    # #
    # plot_convergence(admm = admm_conv)
    # plot_objective(admm=admm_aug_obj)

    # plot_substation_power(copfVals,admmVals,enappVals)
    # plot_battery_soc(copfVals,admmVals,enappVals)
    # plot_reactive_power_flows(copfVals,admmVals,enappVals)
    # plot_der_reactive_power(copfVals,admmVals,enappVals)
    # plot_battery_charging_discharging_combined(copfVals,admmVals,enappVals)
    # plot_active_power_flows(copfVals,admmVals,enappVals)
    # plot_voltage(copfVals,admmVals,enappVals)

    # plot_substation_power(admmVals,admm_opendssVals)
    # plot_battery_soc(admmVals,admm_opendssVals)
    # plot_reactive_power_flows(admmVals,admm_opendssVals)
    # plot_der_reactive_power(admmVals,admm_opendssVals)
    # plot_battery_charging_discharging_combined(admmVals,admm_opendssVals)
    # plot_active_power_flows(admmVals,admm_opendssVals)
    # plot_voltage(admmVals,admm_opendssVals)

    # plot_substation_power(enappVals, enapp_opendssVals)
    # plot_battery_soc(enappVals, enapp_opendssVals)
    # plot_reactive_power_flows(enappVals, enapp_opendssVals)
    # plot_der_reactive_power(enappVals, enapp_opendssVals)
    # plot_battery_charging_discharging_combined(enappVals, enapp_opendssVals)
    # plot_active_power_flows(enappVals, enapp_opendssVals)
    # plot_voltage(enappVals, enapp_opendssVals)

    # plot_convergence(enapp_conv= enapp_conv,admm_conv=admm_conv)
    # plot_objective(enapp_obj=enapp_obj,admm_aug_obj=admm_aug_obj,copf_obj = copfVals['objective_value'])

    # # Calculating Metrics to include in paper
    # print("OPENDSS...")
    # print(f"Total substation Real Power Flows: {sum(opendssVals['P_subs'].values())}")
    # print(f"Total substation Reactive Power Flows: {sum(opendssVals['Q_subs'].values())}")
    # print(f"Total reactive power from PV : {sum(opendssVals['q_D'].values())}")
    # print(f"Total battery Charging Power : {sum(opendssVals['P_c'].values())}")
    # print(f"Total battery Discharging Power : {sum(opendssVals['P_d'].values())}")

