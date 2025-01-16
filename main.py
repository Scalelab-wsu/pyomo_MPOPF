# %%
from Parser.parse import parse_all_data
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import substation_power_minimize,pyomo_solve,power_flow,loss_minimize,cost_minimize
from Build_Model.store import store_results
from Distributed.separate_areas import split_data_into_areas
from Plot.Plotting import *
from OpendssValidate import *
import pandas as pd
import os
import numpy as np
from pyomo.environ import value
from Distributed.admm_test import solve_ADMM
from Distributed.enapp import solve_EnAPP
area_info = {
    'area1': {
        # Area connection information
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
        'up_area': ['area2'],
        'up_global_node_id': [125],
        'up_local_node_id': ['D42'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir' : 'area4'
    }
}

# Set display options to show all rows and columns
pd.set_option('display.max_rows', None)      # Show all rows
pd.set_option('display.max_columns', None)   # Show all columns
pd.set_option('display.width', None)         # Automatically adjust display width
pd.set_option('display.max_colwidth', None)

wd = os.getcwd()
filepath = os.path.join(wd, "raw data", "IEEE_123_other")

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
# %%
if __name__ == "__main__":
    centralized = True
    ADMM = False
    enAPP = True

    if centralized:
        print("Solving centralized problem...")
        centralized_model = build_pyomo_model(data)
        centralized_model = pyomo_solve(centralized_model, loss_minimize)
        copfVals = store_results(centralized_model)
        print(f"Centralized Objective Value: {copfVals['objective_value']}")

    if ADMM:
        print("Solving ADMM ...")
        data_area = split_data_into_areas(data, area_info)
        admmVals = solve_ADMM(data, data_area, area_info, rho=0.5, max_iterations=150)
        print("ADMM ran successfully")

    if enAPP:
        print("Solving EnAPP...")
        data_area = split_data_into_areas(data, area_info)
        enappVals = solve_EnAPP(data, data_area, area_info, max_iterations = 50)
        print("EnAPP ran successfully")



# %%
# model.pprint()
#
# OpendssVals = run_opendss_validation(data, modelvals)
# plot_substation_power(modelvals)
# plot_battery_soc(modelvals,OpendssVals)
# plot_reactive_power_flows(modelvals,OpendssVals)
# plot_der_reactive_power(modelvals,OpendssVals)
# plot_battery_charging_discharging_combined(modelvals,OpendssVals)
# plot_active_power_flows(modelvals,OpendssVals)
# plot_voltage(modelvals,OpendssVals)
#
