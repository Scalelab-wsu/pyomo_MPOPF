# %%
from Parser.parse import parse_all_data
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize
from Build_Model.store import store_results
from Distributed.separate_areas import split_data_into_areas
import pandas as pd
import os
from Distributed.admm_different import solve_ADMM
from Distributed.enapp import solve_EnAPP
from OpendssValidate_new import run_opendss_validation
# from OpendssValidate import run_opendss_validation
from Plot.Plotting import *
area_info = {
    'area1': {
        # Area connection information
        'is_root': True,
        'up_area': [],
        'up_global_node_id': [1],
        'up_local_node_id': [1],
        'down_areas': ['area2', 'area3'],
        'down_local_node_id': ['D12', 'D13'],
        'down_global_node_id': [15, 20],
        'data_dir' : 'area1'
    },
    'area2': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': [117],
        'up_local_node_id': ['D21'],
        'down_areas': ['area4'],
        'down_local_node_id': ['D24'],
        'down_global_node_id': [62],
        'data_dir' : 'area2'
    },
    'area3': {
        # Area connection information
        'is_root': False,
        'up_area': ['area1'],
        'up_global_node_id': [118],
        'up_local_node_id': ['D31'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area3'

    },
    'area4': {
        # Area connection information
        'is_root': False,
        'up_area': ['area2'],
        'up_global_node_id': [125],
        'up_local_node_id': ['D42'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area4'
    }
}

wd = os.getcwd()
filepath = os.path.join(wd, "rawData", "IEEE_123_other","csvs")

# Import CSV files
bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
price = [
    0.026, 0.025, 0.022, 0.02, 0.022, 0.024, 0.025, 0.026,
    0.028, 0.034, 0.038, 0.035, 0.036, 0.037, 0.038, 0.04,
    0.04, 0.03, 0.031, 0.029, 0.027, 0.025, 0.023, 0.026]

data = parse_all_data(bus_data, branch_data, gen_data, bat_data, loadshape_data,pvshape_data,price)
# from rawData.IEEE_123_other.dss_scripts.write_dss_scripts import create_opendss_scripts
# create_opendss_scripts(data)
# %%
if __name__ == "__main__":
    centralized = True
    ADMM = True
    enAPP = True

    if centralized:
        print("Solving centralized problem...")
        centralized_model = build_pyomo_model(data)
        centralized_model = pyomo_solve(centralized_model, cost_minimize)
        copfVals = store_results(centralized_model)
        print(f"Centralized Objective Value: {copfVals['objective_value']}")

    if ADMM:
        print("Solving ADMM ...")
        data_area = split_data_into_areas(data, area_info)
        admmVals,admm_obj,admm_aug_obj,admm_conv = solve_ADMM(data, data_area, area_info, rho=50, max_iterations=500)
        print("ADMM ran successfully")

    if enAPP:
        print("Solving EnAPP...")
        data_area = split_data_into_areas(data, area_info)
        enappVals,enapp_obj,enapp_conv = solve_EnAPP(data, data_area, area_info, max_iterations = 50)
        print("EnAPP ran successfully")
    # %%
    copf_opendssVals = run_opendss_validation(data,copfVals)
    # admm_opendssVals = run_opendss_validation(data, admmVals)
    enapp_opendssVals = run_opendss_validation(data, enappVals)

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
    plot_convergence(enapp_conv,admm_conv)
    plot_objective(enapp_obj,admm_obj,admm_aug_obj)




