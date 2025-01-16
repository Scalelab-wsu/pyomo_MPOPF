from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize,loss_minimize
from Parser.parse import parse_all_data
from separate_areas import split_data_into_areas
from Build_Model.store import store_results
from pyomo.environ import value
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
    data_areas['v_max'] = {key: 1.1 for key in data_areas['v_max'].keys()}
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
    area_name = model.area_name
    area_info = model.area_info
    shared_vars = model.shared_vars
    dual_vars = model.dual_vars
    rho = model.rho

    f = loss_minimize(model)

    for tt in model.Tset:
        t = tt-1
        # Handle upstream connections
        for idx, up_area in enumerate(area_info[area_name]['up_area']):
            local_node_id = area_info[area_name]['up_local_node_id'][idx]
            for ph_idx, ph in enumerate("abc"):
                shared_p = shared_vars[f"{area_name}_{up_area}_p"][-1]
                shared_q = shared_vars[f"{area_name}_{up_area}_q"][-1]
                shared_v = shared_vars[f"{area_name}_{up_area}_v"][-1]
                dual_p = dual_vars[f"lambda_{area_name}_{up_area}_p"][-1]
                dual_q = dual_vars[f"lambda_{area_name}_{up_area}_q"][-1]
                dual_v = dual_vars[f"lambda_{area_name}_{up_area}_v"][-1]

                x_p = sum(model.P[tt, i, k, ph] for (i, k) in model.Lset if i == local_node_id )
                x_q = sum(model.Q[tt, i, k, ph] for (i, k) in model.Lset if i == local_node_id)
                x_v = sum(model.v[tt, i, ph] for i in model.Nset if i == local_node_id)

                f += (
                        dual_p[t][ph_idx] * (x_p - shared_p[t][ph_idx]) +
                        dual_q[t][ph_idx] * (x_q - shared_q[t][ph_idx]) +
                        dual_v[t][ph_idx] * (
                                    x_v - shared_v[t][ph_idx] ** 2) +
                        (rho / 2) * (
                                np.square(
                                    x_p - shared_p[t][ph_idx]) +
                                np.square(
                                    x_q - shared_q[t][ph_idx]) +
                                np.square(
                                    x_v - shared_v[t][ph_idx] ** 2)
                        )
                )

        # Handle downstream connections
        for idx, down_area in enumerate(area_info[area_name]['down_areas']):
            local_node_id = area_info[area_name]['down_local_node_id'][idx]
            for ph_idx, ph in enumerate("abc"):
                shared_p = shared_vars[f"{area_name}_{down_area}_p"][-1]
                shared_q = shared_vars[f"{area_name}_{down_area}_q"][-1]
                shared_v = shared_vars[f"{area_name}_{down_area}_v"][-1]
                dual_p = dual_vars[f"lambda_{area_name}_{down_area}_p"][-1]
                dual_q = dual_vars[f"lambda_{area_name}_{down_area}_q"][-1]
                dual_v = dual_vars[f"lambda_{area_name}_{down_area}_v"][-1]

                x_p = sum(model.P[tt, i, k, ph] for (i, k) in model.Lset if i == local_node_id)
                x_q = sum(model.Q[tt, i, k, ph] for (i, k) in model.Lset if i == local_node_id)
                x_v = sum(model.v[tt, i, ph] for i in model.Nset if i == local_node_id)

                f += (
                        dual_p[t][ph_idx] * (x_p - shared_p[t][ph_idx]) +
                        dual_q[t][ph_idx] * (x_q - shared_q[t][ph_idx]) +
                        dual_v[t][ph_idx] * (
                                x_v - shared_v[t][ph_idx] ** 2) +
                        (rho / 2) * (
                                np.square(
                                    x_p - shared_p[t][ph_idx]) +
                                np.square(
                                    x_q - shared_q[t][ph_idx]) +
                                np.square(
                                    x_v - shared_v[t][ph_idx] ** 2)
                        )
                )

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
    rho = 0.5  # You can make rho a parameter if needed

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

        max_diff = 0  # For convergence checking

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
                p_local[f"{area}_{conn_area}_p"] = np.vstack([area_p[key] for key in area_p.keys() if key[1][0] == local_node_id]).reshape((-1, 3))
                q_local[f"{area}_{conn_area}_q"] = np.vstack([area_q[key] for key in area_q.keys() if key[1][0] == local_node_id]).reshape((-1, 3))
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
            area_update = data_by_area[area]
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                local_node_id = area_info[area]['down_local_node_id'][idx]
                for t in area_update['Tset']:
                    for ph in "abc":
                        area_update['p_L'][t,local_node_id,ph] = p_global[f"{conn_area}_{area}_p"][t-1]["abc".index(ph)]
                        area_update['q_L'][t,local_node_id,ph] = q_global[f"{conn_area}_{area}_q"][t-1]["abc".index(ph)]
                        data_by_area[conn_area]['v_swing'][local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t-1]["abc".index(ph)]

            for idx, conn_area in enumerate(area_info[area]['up_area']):
                local_node_id = area_info[area]['up_local_node_id'][idx]
                for t in area_update['Tset']:
                    for ph in "abc":
                        area_update['p_L'][t, local_node_id, ph] = p_global[f"{conn_area}_{area}_p"][t - 1]["abc".index(ph)]
                        area_update['q_L'][t, local_node_id, ph] = q_global[f"{conn_area}_{area}_q"][t - 1]["abc".index(ph)]
                        area_update['v_swing'][local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]

        # Update dual variables
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
                lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
                lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])

            for idx, conn_area in enumerate(area_info[area]['up_area']):
                lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
                lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
                lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])

        # Share global variables and dual variables
        for area in area_folders:
            for idx, conn_area in enumerate(area_info[area]['down_areas']):
                shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"].copy())
                shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"].copy())
                shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"].copy())

            for idx, conn_area in enumerate(area_info[area]['up_area']):
                shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"].copy())
                shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"].copy())
                shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"].copy())
                dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"].copy())
        ## Convergence Check
        max_diff = {}

        for area in area_folders:
            max_diff[area] = []  # Initialize a list to store the max differences for the area

            # Iterate over down_areas
            for conn_area in area_info[area]['down_areas']:
                max_diff[area].append(max(
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_p"][-1] - shared_vars[f"{area}_{conn_area}_p"][-2]) ** 2)),
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_q"][-1] - shared_vars[f"{area}_{conn_area}_q"][-2]) ** 2)),
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_v"][-1] - shared_vars[f"{area}_{conn_area}_v"][-2]) ** 2)),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_p"][-1] - dual_vars[f"lambda_{area}_{conn_area}_p"][-2]) ** 2),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_q"][-1] - dual_vars[f"lambda_{area}_{conn_area}_q"][-2]) ** 2),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_v"][-1] - dual_vars[f"lambda_{area}_{conn_area}_v"][-2]) ** 2)
                ))

            # Iterate over up_area
            for conn_area in area_info[area]['up_area']:
                max_diff[area].append(max(
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_p"][-1] - shared_vars[f"{area}_{conn_area}_p"][-2]) ** 2)),
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_q"][-1] - shared_vars[f"{area}_{conn_area}_q"][-2]) ** 2)),
                    np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_v"][-1] - shared_vars[f"{area}_{conn_area}_v"][-2]) ** 2)),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_p"][-1] - dual_vars[f"lambda_{area}_{conn_area}_p"][-2]) ** 2),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_q"][-1] - dual_vars[f"lambda_{area}_{conn_area}_q"][-2]) ** 2),
                    np.max(np.linalg.norm(dual_vars[f"lambda_{area}_{conn_area}_v"][-1] - dual_vars[f"lambda_{area}_{conn_area}_v"][-2]) ** 2)
                ))

        # Print statement for debugging
        tol = np.max([np.max(sublist) for sublist in max_diff.values()])
        convergence[i] = tol
        # objective[i] = sum([data[area][6] for area in area_folders])
        objective[i] = sum([area_results['area1']['objective_value']])
        # print(f"iteration = {i}, tolerance={tol}, objective value: {sum([data[area][6] for area in area_folders])}")
        print(f"iteration = {i}, tolerance={tol}, objective value: {sum([area_results['area1']['objective_value']])}")
        if tol < 1e-6 :
            print(f"Converged after {i} iterations")
            # print(f"total objective value for DOPF:{sum([data[area][6] for area in area_folders])}")
            print(f"total objective value for DOPF:{sum([area_results['area1']['objective_value']])}")
            break

    pool.close()
    pool.join()

    print(f"Time taken for DOPF: {perf_counter() - tic} seconds")