from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize,loss_minimize
from Parser.parse import parse_all_data
from separate_areas_test import split_data_into_areas
from Build_Model.store import store_results
from pyomo.environ import value,sqrt
import os
import pandas as pd
import numpy as np
import multiprocessing as mp
from multiprocessing import Manager
from time import perf_counter

wd = os.getcwd()
print(wd)
filepath = os.path.join(wd,"..", "raw data", "IEEE_123_other")


###########################
# 2) area_info structure
###########################
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

def process_area(data_areas,area_name,area_info, shared_vars, dual_vars, rho):
    data_areas['v_max'] = {key: 1.06 for key in data_areas['v_max'].keys()}
    model = build_pyomo_model(data_areas)

    model = pyomo_solve(
        model,
        obj_none_relaxed_area,
        area_name=area_name,
        area_info=area_info,
        shared_vars=shared_vars,
        dual_vars=dual_vars,
        rho=rho
    )
    solutions = store_results(model)
    return area_name, solutions

def obj_none_relaxed_area(model, **kwargs):
    area = model.area_name
    area_info = model.area_info
    shared_vars = model.shared_vars
    dual_vars = model.dual_vars
    rho = model.rho

    f = loss_minimize(model)

    ## creating vectors of current and previous lambda and globals
    shared_list_current = []
    dual_list_current = []

    # Iterate over each area in the area_folders
    for conn_area in area_info[area]['down_areas']:
        current_shared_p = shared_vars[f"{area}_{conn_area}_p"][-1].flatten()
        current_shared_q = shared_vars[f"{area}_{conn_area}_q"][-1].flatten()
        current_shared_v = shared_vars[f"{area}_{conn_area}_v"][-1].flatten()
        shared_list_current.extend([current_shared_p, current_shared_q, current_shared_v])

        current_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-1].flatten()
        current_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-1].flatten()
        current_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-1].flatten()
        dual_list_current.extend([current_dual_p, current_dual_q, current_dual_v])

    for conn_area in area_info[area]['up_area']:
        current_shared_p = shared_vars[f"{area}_{conn_area}_p"][-1].flatten()
        current_shared_q = shared_vars[f"{area}_{conn_area}_q"][-1].flatten()
        current_shared_v = shared_vars[f"{area}_{conn_area}_v"][-1].flatten()
        shared_list_current.extend([current_shared_p, current_shared_q, current_shared_v])

        current_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-1].flatten()
        current_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-1].flatten()
        current_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-1].flatten()
        dual_list_current.extend([current_dual_p, current_dual_q, current_dual_v])

    # Convert the lists to NumPy vectors
    shared_vector_current = np.concatenate(shared_list_current)
    dual_vector_current = np.concatenate(dual_list_current)

    vars_list = []
    ## similarly creating vectors of variables
    # Handle downstream connections
    for idx, down_area in enumerate(area_info[area]['down_areas']):
        local_node_id = area_info[area]['down_local_node_id'][idx]
        x_p = [model.P[t, (i, k), ph] for t in model.Tset for (i, k) in model.Lset if k == local_node_id for ph in model.phases]
        x_q = [model.Q[t, (i, k), ph] for t in model.Tset for (i, k) in model.Lset if k == local_node_id for ph in model.phases]
        x_v = [model.v[t, i, ph] for t in model.Tset for i in model.Nset if i == local_node_id for ph in model.phases]
        vars_list.extend([x_p, x_q, x_v])

    # Handle upstream connections
    for idx, up_area in enumerate(area_info[area]['up_area']):
        local_node_id = area_info[area]['up_local_node_id'][idx]
        x_p = [model.P_subs[t,ph] for t in model.Tset for ph in model.phases]
        x_q = [model.Q_subs[t,ph] for t in model.Tset for ph in model.phases]
        x_v = [model.v[t, i, ph] for t in model.Tset for i in model.Nset if i == local_node_id for ph in model.phases]
        vars_list.extend([x_p, x_q, x_v])

    # Flatten vars_list into a single list of variables
    vars_list_vector = np.concatenate(vars_list)

    # Compute penalty_term and convergence_term using Pyomo's symbolic operations
    penalty_term = sum(
        lambda_i * (x_i - y_i)
        for lambda_i, x_i, y_i in zip(dual_vector_current, vars_list_vector, shared_vector_current)
    )

    convergence_term = sum(
        (x_i - y_i) ** 2
        for x_i, y_i in zip(vars_list_vector, shared_vector_current)
    )

    # Update the objective function with dual and penalty expressions
    f += penalty_term + (rho/2)*convergence_term


    return f

if __name__ == "__main__":
    tic = perf_counter()
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

    data = parse_all_data(bus_data, branch_data, gen_data, bat_data, loadshape_data, pvshape_data, price)
    data_by_area = split_data_into_areas(data)
    area_folders = ['area1', 'area2', 'area3', 'area4']
    base_path = os.getcwd()  # Set base_path dynamically

    # Initialize global shared variables for the iteration
    shared_vars = {}
    dual_vars = {}
    rho = 5  # You can make rho a parameter if needed

    # Initialize shared variables and dual variables dynamically
    for area in area_folders:
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            shared_vars[f"{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_v"] = [np.ones((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_v"] = [np.zeros((data['T'], 3))]
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            shared_vars[f"{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_v"] = [np.ones((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{area}_{conn_area}_v"] = [np.zeros((data['T'], 3))]

    convergence = {}
    objective = {}

    pool = mp.Pool(processes=len(area_folders))

    max_iterations = 50
    for i in range(max_iterations):
        results = pool.starmap(process_area, [(data_by_area[area],area,area_info,shared_vars,dual_vars,rho) for area in area_folders])
        area_results = {area_name: solutions for area_name, solutions in results}

        p_local = {}
        q_local = {}
        v_local = {}
        p_global = {}
        q_global = {}
        v_global = {}
        lagrange_update = {}

        # Extract local variables
        for area in area_folders:
            area_p = area_results[area]['P']
            area_q = area_results[area]['Q']
            area_v = area_results[area]['v']
            for idx, conn_area in enumerate(area_info[area]['up_area']):
                local_node_id = area_info[area]['up_local_node_id'][idx]
                p_local[f"{area}_{conn_area}_p"] = np.vstack([area_results[area]['P_subs'][key] for key in area_results[area]['P_subs'].keys()]).reshape((-1, 3))
                q_local[f"{area}_{conn_area}_q"] = np.vstack([area_results[area]['Q_subs'][key] for key in area_results[area]['Q_subs'].keys()]).reshape((-1, 3))
                v_local[f"{area}_{conn_area}_v"] = np.vstack([area_v[key] for key in area_v.keys() if key[1] == local_node_id]).reshape((-1, 3))

            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                local_node_id = area_info[area]['down_local_node_id'][idx]
                p_local[f"{area}_{conn_area}_p"] = np.vstack([area_p[key] for key in area_p.keys() if key[1][1] == local_node_id]).reshape((-1, 3))
                q_local[f"{area}_{conn_area}_q"] = np.vstack([area_q[key] for key in area_q.keys() if key[1][1] == local_node_id]).reshape((-1, 3))
                v_local[f"{area}_{conn_area}_v"] = np.vstack([area_v[key] for key in area_v.keys() if key[1] == local_node_id]).reshape((-1, 3))

        # Compute global variables as averages
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                p_global[f"{area}_{conn_area}_p"] = (p_local[f"{area}_{conn_area}_p"] + p_local[f"{conn_area}_{area}_p"]) / 2
                q_global[f"{area}_{conn_area}_q"] = (q_local[f"{area}_{conn_area}_q"] + q_local[f"{conn_area}_{area}_q"]) / 2
                v_global[f"{area}_{conn_area}_v"] = (v_local[f"{area}_{conn_area}_v"] + v_local[f"{conn_area}_{area}_v"]) / 2

            for idx, conn_area in enumerate(area_info[area]['up_area']):
                p_global[f"{area}_{conn_area}_p"] = (p_local[f"{area}_{conn_area}_p"] + p_local[f"{conn_area}_{area}_p"]) / 2
                q_global[f"{area}_{conn_area}_q"] = (q_local[f"{area}_{conn_area}_q"] + q_local[f"{conn_area}_{area}_q"]) / 2
                v_global[f"{area}_{conn_area}_v"] = (v_local[f"{area}_{conn_area}_v"] + v_local[f"{conn_area}_{area}_v"]) / 2

        ## updating data_by_areas dictionary
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                local_node_id = area_info[area]['down_local_node_id'][idx]
                for t in data_by_area[area]['Tset']:
                    for ph in "abc":
                        data_by_area[area]['p_L'][t,local_node_id,ph] = p_global[f"{conn_area}_{area}_p"][t-1]["abc".index(ph)]
                        data_by_area[area]['q_L'][t,local_node_id,ph] = q_global[f"{conn_area}_{area}_q"][t-1]["abc".index(ph)]
                        data_by_area[conn_area]['v_swing'][local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t-1]["abc".index(ph)]
                        # data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]

            for idx, conn_area in enumerate(area_info[area]['up_area']):
                local_node_id = area_info[area]['up_local_node_id'][idx]
                for t in data_by_area[area]['Tset']:
                    for ph in "abc":
                        data_by_area[area]['p_L'][t, local_node_id, ph] = -p_global[f"{conn_area}_{area}_p"][t - 1]["abc".index(ph)]
                        data_by_area[area]['q_L'][t, local_node_id, ph] = -q_global[f"{conn_area}_{area}_q"][t - 1]["abc".index(ph)]
                        data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]

        ##updating the lagranges multipliers
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
                lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
                lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])
            for idx, conn_area in enumerate(area_info[area]['up_area']):
                lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
                lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
                lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])

        ## sharing the global and dual variables
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"])
                shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"])
                shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"])
                dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"])
                dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"])
                dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"])
            for idx, conn_area in enumerate(area_info[area]['up_area']):
                shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"])
                shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"])
                shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"])
                dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"])
                dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"])
                dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"])

        ## creating vectors of current and previous lambda and globals
        # Initialize lists to collect shared and dual variables
        shared_list_current = []
        shared_list_previous = []
        dual_list_current = []
        dual_list_previous = []

        # Iterate over each area in the area_folders
        for area in area_folders:
            for conn_area in area_info[area]['down_areas']:
                current_shared_p = shared_vars[f"{area}_{conn_area}_p"][-1].flatten()
                current_shared_q = shared_vars[f"{area}_{conn_area}_q"][-1].flatten()
                current_shared_v = shared_vars[f"{area}_{conn_area}_v"][-1].flatten()
                shared_list_current.extend([current_shared_p, current_shared_q, current_shared_v])

                current_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-1].flatten()
                current_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-1].flatten()
                current_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-1].flatten()
                dual_list_current.extend([current_dual_p, current_dual_q, current_dual_v])

                previous_shared_p = shared_vars[f"{area}_{conn_area}_p"][-2].flatten()
                previous_shared_q = shared_vars[f"{area}_{conn_area}_q"][-2].flatten()
                previous_shared_v = shared_vars[f"{area}_{conn_area}_v"][-2].flatten()
                shared_list_previous.extend([previous_shared_p, previous_shared_q, previous_shared_v])

                previous_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-2].flatten()
                previous_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-2].flatten()
                previous_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-2].flatten()
                dual_list_previous.extend([previous_dual_p, previous_dual_q, previous_dual_v])
            for conn_area in area_info[area]['up_area']:
                current_shared_p = shared_vars[f"{area}_{conn_area}_p"][-1].flatten()
                current_shared_q = shared_vars[f"{area}_{conn_area}_q"][-1].flatten()
                current_shared_v = shared_vars[f"{area}_{conn_area}_v"][-1].flatten()
                shared_list_current.extend([current_shared_p, current_shared_q, current_shared_v])

                current_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-1].flatten()
                current_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-1].flatten()
                current_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-1].flatten()
                dual_list_current.extend([current_dual_p, current_dual_q, current_dual_v])

                previous_shared_p = shared_vars[f"{area}_{conn_area}_p"][-2].flatten()
                previous_shared_q = shared_vars[f"{area}_{conn_area}_q"][-2].flatten()
                previous_shared_v = shared_vars[f"{area}_{conn_area}_v"][-2].flatten()
                shared_list_previous.extend([previous_shared_p, previous_shared_q, previous_shared_v])

                previous_dual_p = dual_vars[f"lambda_{area}_{conn_area}_p"][-2].flatten()
                previous_dual_q = dual_vars[f"lambda_{area}_{conn_area}_q"][-2].flatten()
                previous_dual_v = dual_vars[f"lambda_{area}_{conn_area}_v"][-2].flatten()
                dual_list_previous.extend([previous_dual_p, previous_dual_q, previous_dual_v])


        # Convert the lists to NumPy vectors
        shared_vector_current = np.concatenate(shared_list_current)
        shared_vector_previous = np.concatenate(shared_list_previous)
        dual_vector_current = np.concatenate(dual_list_current)
        dual_vector_previous = np.concatenate(dual_list_previous)

        ## Convergence Check

        lambda_check = np.square(np.linalg.norm(dual_vector_current - dual_vector_previous))
        global_check = rho * np.square(np.linalg.norm(shared_vector_current - shared_vector_previous))


        tol = max(global_check,global_check)
        convergence[i] = tol
        # objective[i] = sum([data[area][6] for area in area_folders])
        objective[i] = area_results['area1']['objective_value']
        # print(f"iteration = {i}, tolerance={tol}, objective value: {sum([data[area][6] for area in area_folders])}")
        print(f"iteration = {i}, tolerance={tol}, objective value: {area_results['area1']['objective_value']}")
        if tol < 1e-6 :
            print(f"Converged after {i} iterations")
            # print(f"total objective value for DOPF:{sum([data[area][6] for area in area_folders])}")
            print(f"total objective value for DOPF:{area_results['area1']['objective_value']}")
            break

    pool.close()
    pool.join()

    print(f"Time taken for DOPF: {perf_counter() - tic} seconds")