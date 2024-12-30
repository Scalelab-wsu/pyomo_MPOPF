# %%
from Parser.parse import parse_all_data
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import substation_power_minimize,pyomo_solve,power_flow,loss_minimize,cost_minimize
from Build_Model.store import store_results
from Plot.Plotting import *
import pandas as pd
import os
import numpy as np

wd = os.getcwd()
print(wd)
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
model = build_pyomo_model(data)

# %%
# model.pprint()
model = pyomo_solve(model,cost_minimize)
# modelvals = store_results(model)
# plot_substation_power(modelvals)
# plot_battery_soc(modelvals)
# plot_reactive_power_flows(modelvals)
# plot_der_reactive_power(modelvals)
# plot_battery_charging_discharging_combined(modelvals)
# plot_active_power_flows(modelvals)