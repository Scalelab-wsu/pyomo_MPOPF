from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize,loss_minimize
from Build_Model.store import store_results
import numpy as np
import multiprocessing as mp
from collections import defaultdict,ChainMap


def process_area(data_areas,area_name,obj_fcn):
    data_areas['v_max'] = {key: 1.1 for key in data_areas['v_max'].keys()}
    model = build_pyomo_model(data_areas)

    model = pyomo_solve(model,obj_fcn)
    solutions = store_results(model)
    return area_name, solutions

def initialize_shared_dual(area_info, data):
    shared_vars = {}

    # Initialize shared variables dynamically
    for area in area_info.keys():
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_v"] = [np.ones((data['T'], 3))]
    return shared_vars

## computing local by alpha sharing
def compute_locals(area_info, area_results,shared_vars,alpha):
    p_local, q_local, v_local = {}, {}, {}
    for area in area_info.keys():
        area_p = area_results[area]['P']
        area_q = area_results[area]['Q']
        area_v = area_results[area]['v']

        # Upstream connections
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            local_node = area_info[area]['up_local_node_id'][idx]
            p_key = f"{area}_{conn_area}_p"
            q_key = f"{area}_{conn_area}_q"
            p_local[p_key] = np.vstack([area_p[key] for key in area_p
                                        if key[1][0] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1][0] == local_node]).reshape((-1, 3))
            ## alpha sharing
            p_local[p_key] = (1 - alpha)*p_local[p_key] + alpha * shared_vars[p_key][-1]
            q_local[q_key] = (1 - alpha) * q_local[q_key] + alpha * shared_vars[q_key][-1]
        # Downstream connections
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            v_key = f"{area}_{conn_area}_v"
            v_local[v_key] = np.vstack([area_v[key] for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))
            ## alpha sharing
            v_local[v_key] = (1 - alpha) * v_local[v_key] + alpha * shared_vars[v_key][-1]
    return p_local, q_local, v_local

def update_area_values(area_info,data_by_area,p_local,q_local,v_local):
    for area in area_info.keys():
        # Update downstream loads
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph_idx, ph in enumerate("abc"):
                    data_by_area[area]['p_L'][t, local_node, ph] = \
                        p_local[f"{conn_area}_{area}_p"][t - 1, ph_idx]
                    data_by_area[area]['q_L'][t, local_node, ph] = \
                        q_local[f"{conn_area}_{area}_q"][t - 1, ph_idx]

        # Update upstream voltages
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            local_node = area_info[area]['up_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph_idx, ph in enumerate("abc"):
                    data_by_area[area]['v_swing'][t, local_node, ph] = \
                        v_local[f"{conn_area}_{area}_v"][t - 1, ph_idx]
    return data_by_area

def share_local(area_info,shared_vars,p_local,q_local,v_local):
    for area in area_info.keys():
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_v"].append(v_local[f"{area}_{conn_area}_v"])
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"].append(p_local[f"{area}_{conn_area}_p"])
            shared_vars[f"{area}_{conn_area}_q"].append(q_local[f"{area}_{conn_area}_q"])

    return shared_vars

def arrange_solution_by_areas(area_info,area_results):
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node_id = area_info[area]['down_local_node_id'][idx]
            global_node_id = area_info[conn_area]['up_global_node_id'][0]
            for key, value in area_results[area].items():
                if key in ['P', 'Q']:  # For 'pij_values': key is (t, i, k)
                    updated_dict = {}
                    for (t, (i, k), ph), val in value.items():
                        if k == local_node_id:
                            updated_dict[(t, (i, global_node_id), ph)] = val
                        else:
                            updated_dict[(t, (i, k), ph)] = val
                    area_results[area][key] = updated_dict

    dopf = defaultdict(dict)
    for area_name, vars_dict in area_results.items():
        for key, value in vars_dict.items():
            dopf[key][area_name] = value

    return dopf

def merge_solutions(dopf):
    ## merging the area_wise dopf dictionary into one
    dopfVals = {}
    # Initialize containers for each variable
    dopfVals['P_subs'] = {}
    dopfVals['Q_subs'] = {}
    dopfVals['P'] = {}
    dopfVals['Q'] = {}
    dopfVals['v'] = {}
    dopfVals['q_D'] = {}
    dopfVals['P_c'] = {}
    dopfVals['P_d'] = {}
    dopfVals['B'] = {}

    dopfVals["P_subs"] = {**dopf['P_subs']['area1']}
    dopfVals["Q_subs"] = {**dopf['Q_subs']['area1']}
    dopfVals["P"] = dict(ChainMap(*[dopf['P'][area] for area in dopf['P']]))
    dopfVals["Q"] = dict(ChainMap(*[dopf['Q'][area] for area in dopf['Q']]))
    dopfVals["v"] = dict(ChainMap(*[dopf['v'][area] for area in dopf['v']]))
    dopfVals["B"] = dict(ChainMap(*[dopf['B'][area] for area in dopf['B']]))
    dopfVals["P_c"] = dict(ChainMap(*[dopf['P_c'][area] for area in dopf['P_c']]))
    dopfVals["P_d"] = dict(ChainMap(*[dopf['P_d'][area] for area in dopf['P_d']]))
    dopfVals["q_D"] = dict(ChainMap(*[dopf['q_D'][area] for area in dopf['q_D']]))

    return dopfVals

def exclude_dummies(dopfVals):
    filtered_dictionaries = {}
    for vars in dopfVals.keys():
        filtered_dictionaries[vars] = {}  # Initialize an empty dictionary for each `vars`
        for key, value in dopfVals[vars].items():
            key1 = key[1]  # Get the second element of the key
            # Check if key[1] is a tuple and contains any strings
            if isinstance(key1, tuple) and any(isinstance(sub, str) for sub in key1):
                continue  # Skip this entry if any string is found in the tuple
            # Check if key[1] is a string directly
            if isinstance(key1, str):
                continue  # Skip this entry if key[1] is a string
            # Otherwise, add it to the new filtered dictionary
            filtered_dictionaries[vars][key] = value
    return filtered_dictionaries
def solve_EnAPP(data, data_by_area, area_info, obj_fcn, max_iterations=50,alpha = 0):
    shared_vars = initialize_shared_dual(area_info, data)
    convergence = {}
    objective = {}
    area_folders = area_info.keys()
    pool = mp.Pool(processes=len(area_folders))

    for i in range(max_iterations):
        results = pool.starmap(process_area,[(data_by_area[area], area, obj_fcn) for area in area_folders])
        area_results = {area_name: solutions for area_name, solutions in results}

        p_local, q_local, v_local = compute_locals(area_info, area_results,shared_vars,alpha)

        data_by_area = update_area_values(area_info, data_by_area, p_local, q_local, v_local)

        shared_vars = share_local(area_info, shared_vars, p_local, q_local, v_local)

        ## Convergence Check
        max_diff = {}

        for area in area_folders:
            max_diff[area] = []  # Initialize a list to store the max differences for the area

            # Iterate over down_areas
            for conn_area in area_info[area]['down_areas']:
                # Compute the maximum difference for 'v' shared variable
                diff_v = np.max(np.abs(shared_vars[f"{area}_{conn_area}_v"][-1] - shared_vars[f"{area}_{conn_area}_v"][-2]))
                max_diff[area].append(diff_v)

            # Iterate over up_area
            for conn_area in area_info[area]['up_area']:
                # Compute the maximum difference for 'p' and 'q' shared variables
                diff_p = np.max(np.abs(shared_vars[f"{area}_{conn_area}_p"][-1] - shared_vars[f"{area}_{conn_area}_p"][-2]))
                diff_q = np.max(np.abs(shared_vars[f"{area}_{conn_area}_q"][-1] - shared_vars[f"{area}_{conn_area}_q"][-2]))
                max_diff[area].append(max(diff_p, diff_q))  # Take the maximum difference of 'p' and 'q'

        # Print statement for debugging
        tol = np.max([np.max(sublist) for sublist in max_diff.values()])
        convergence[i] = tol
        if obj_fcn == loss_minimize:
            objective[i] = [sum([area_results[area]['objective_value'] for area in area_folders])]
        if obj_fcn == cost_minimize:
            objective[i] = [area_results['area1']['objective_value']]

        print(f"iteration = {i}, tolerance={tol}, objective value: {objective[i]}")
        if tol < 1e-5 :
            print(f"Converged after {i} iterations")
            print(f"total objective value for DOPF:{objective[i]}")
            break
        alpha = alpha/2

    pool.close()
    pool.join()

    dopf = arrange_solution_by_areas(area_info, area_results)

    dopfVals = merge_solutions(dopf)
    dopfVals = exclude_dummies(dopfVals)

    return dopfVals,objective,convergence