# %%
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize,loss_minimize
from Build_Model.store import store_results
from pyomo.environ import value,sqrt
import numpy as np
import multiprocessing as mp
from collections import defaultdict,ChainMap


def process_area(data_areas,area_name,area_info, shared_vars, dual_vars, rho):
    data_areas['v_max'] = {key: 1.1 for key in data_areas['v_max'].keys()}
    model = build_pyomo_model(data_areas)

    model = pyomo_solve(
        model,
        augmented_obj_function,
        area_name=area_name,
        area_info=area_info,
        shared_vars=shared_vars,
        dual_vars=dual_vars,
        rho=rho
    )
    solutions = store_results(model)

    original_objective_value = value(model.original_obj)  # Convert Pyomo expression to numerical value

    augmented_objective_value = value(model.obj)  # Assuming 'obj' is the name of the objective

    solutions['original_objective'] = original_objective_value
    solutions['augmented_objective'] = augmented_objective_value

    return area_name, solutions

def augmented_obj_function(model, **kwargs):
    area = model.area_name
    area_info = model.area_info
    shared_vars = model.shared_vars
    dual_vars = model.dual_vars
    rho = model.rho

    original_obj = loss_minimize(model)

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
        x_p = [model.P[t, (i, k), ph] for t in model.Tset for (i, k) in model.Lset if i == local_node_id for ph in model.phases]
        x_q = [model.Q[t, (i, k), ph] for t in model.Tset for (i, k) in model.Lset if i == local_node_id for ph in model.phases]
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
    augmented_obj = original_obj + penalty_term + (rho/2)*convergence_term

    model.original_obj = original_obj

    return augmented_obj

def initialize_shared_dual(area_info, data):
    shared_vars = {}
    dual_vars = {}

    # Initialize shared variables and dual variables dynamically
    for area in area_info.keys():
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

    return shared_vars, dual_vars

def compute_locals(area_info,area_results):
    p_local = {}
    q_local = {}
    v_local = {}

    # Extract local variables
    for area in area_info.keys():
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

    return p_local, q_local, v_local

def compute_globals(area_info,p_local,q_local,v_local):
    p_global = {}
    q_global = {}
    v_global = {}

    # Compute global variables as averages
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            p_global[f"{area}_{conn_area}_p"] = (p_local[f"{area}_{conn_area}_p"] + p_local[f"{conn_area}_{area}_p"]) / 2
            q_global[f"{area}_{conn_area}_q"] = (q_local[f"{area}_{conn_area}_q"] + q_local[f"{conn_area}_{area}_q"]) / 2
            v_global[f"{area}_{conn_area}_v"] = (v_local[f"{area}_{conn_area}_v"] + v_local[f"{conn_area}_{area}_v"]) / 2

        for idx, conn_area in enumerate(area_info[area]['up_area']):
            p_global[f"{area}_{conn_area}_p"] = (p_local[f"{area}_{conn_area}_p"] + p_local[f"{conn_area}_{area}_p"]) / 2
            q_global[f"{area}_{conn_area}_q"] = (q_local[f"{area}_{conn_area}_q"] + q_local[f"{conn_area}_{area}_q"]) / 2
            v_global[f"{area}_{conn_area}_v"] = (v_local[f"{area}_{conn_area}_v"] + v_local[f"{conn_area}_{area}_v"]) / 2

    return p_global, q_global, v_global

def update_area_values(area_info,data_by_area,p_global,q_global,v_global):
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node_id = area_info[area]['down_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph in "abc":
                    data_by_area[area]['p_L'][t,local_node_id,ph] = p_global[f"{conn_area}_{area}_p"][t-1]["abc".index(ph)]
                    data_by_area[area]['q_L'][t,local_node_id,ph] = q_global[f"{conn_area}_{area}_q"][t-1]["abc".index(ph)]
                    data_by_area[conn_area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t-1]["abc".index(ph)]
                    # data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]

        for idx, conn_area in enumerate(area_info[area]['up_area']):
            local_node_id = area_info[area]['up_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph in "abc":
                    data_by_area[area]['p_L'][t, local_node_id, ph] = p_global[f"{conn_area}_{area}_p"][t - 1]["abc".index(ph)]
                    data_by_area[area]['q_L'][t, local_node_id, ph] = q_global[f"{conn_area}_{area}_q"][t - 1]["abc".index(ph)]
                    data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]

    return data_by_area

def update_lagrange(area_info,dual_vars,p_local,q_local,v_local,p_global,q_global,v_global,rho):
    lagrange_update = {}
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
            lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
            lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"])
            lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"])
            lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"])

    return lagrange_update

def share_global_dual(area_info,shared_vars,dual_vars,lagrange_update,p_global,q_global,v_global):
    for area in area_info.keys():
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

    return shared_vars,dual_vars

def create_vectors(shared_vars,dual_vars,area_info):

    shared_list_current = []
    shared_list_previous = []
    dual_list_current = []
    dual_list_previous = []

    # Iterate over each area in the area_folders
    for area in area_info.keys():
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

    return shared_vector_previous, shared_vector_current, dual_vector_current, dual_vector_previous

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


def solve_ADMM(data, data_by_area, area_info, rho, max_iterations):
    shared_vars, dual_vars = initialize_shared_dual(area_info, data)

    convergence = {}
    objective = {}
    area_folders = area_info.keys()
    pool = mp.Pool(processes=len(area_folders))

    for i in range(max_iterations):
        results = pool.starmap(process_area,
                               [(data_by_area[area], area, area_info, shared_vars, dual_vars, rho) for area in
                                area_folders])
        area_results = {area_name: solutions for area_name, solutions in results}

        p_local, q_local, v_local = compute_locals(area_info, area_results)

        p_global, q_global, v_global = compute_globals(area_info, p_local, q_local, v_local)

        data_by_area = update_area_values(area_info, data_by_area, p_global, q_global, v_global)

        lagrange_update = update_lagrange(area_info, dual_vars, p_local, q_local, v_local, p_global, q_global, v_global,
                                          rho)

        shared_vars, dual_vars = share_global_dual(area_info, shared_vars, dual_vars, lagrange_update, p_global,
                                                   q_global, v_global)

        shared_vector_previous, shared_vector_current, dual_vector_current, dual_vector_previous = create_vectors(
            shared_vars, dual_vars, area_info)

        ## Convergence Check

        lambda_check = np.square(np.linalg.norm(dual_vector_current - dual_vector_previous))
        global_check = rho * np.square(np.linalg.norm(shared_vector_current - shared_vector_previous))

        tol = max(global_check, lambda_check)
        convergence[i] = tol
        # objective[i] = sum([data[area][6] for area in area_folders])
        objective[i] = area_results['area1']['objective_value']
        print(
            f"iteration = {i}, tolerance={tol}, objective value: {sum([area_results[area]['objective_value'] for area in area_folders])},original obj:{sum(area_results[area]['original_objective'] for area in area_folders)}, augmented obj = {sum(area_results[area]['augmented_objective'] for area in area_folders)}")
        # print(f"iteration = {i}, tolerance={tol}, objective value: {area_results['area1']['objective_value']},original obj:{area_results['area1']['original_objective']}, augmented obj = {area_results['area1']['augmented_objective']}")
        if tol < 1e-6:
            print(f"Converged after {i} iterations")
            print(
                f"total objective value for DOPF:{sum([area_results[area]['objective_value'] for area in area_folders])}")
            # print(f"total objective value for DOPF:{area_results['area1']['objective_value']}")
            break

    pool.close()
    pool.join()


    dopf = arrange_solution_by_areas(area_info, area_results)

    dopfVals = merge_solutions(dopf)

    return dopfVals

