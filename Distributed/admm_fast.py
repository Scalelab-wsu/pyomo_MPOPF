
from Build_Model.Constraints_new import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize,loss_minimize
from Build_Model.store import store_results
import numpy as np
import multiprocessing as mp
from collections import defaultdict,ChainMap
from pyomo.environ import value

# Worker initialization function
def init_worker():
    global _model_cache
    _model_cache = {}

def process_area(data_areas,area_name,area_info, shared_vars, dual_vars, rho,obj_fcn,prev_solution = None):
    global _model_cache
    if area_name not in _model_cache:
        data_areas['v_max'] = {key: 1.1 for key in data_areas['v_max'].keys()}
        model = build_pyomo_model(data_areas)
        _model_cache[area_name] = model
    else:
        model = _model_cache[area_name]
    if area_name != 'area1':
        model.substation_voltage_magnitude.deactivate()

    # Parameter updates remain the same
    for index in model.p_L:
        model.p_L[index].value = data_areas['p_L'][index]
    for index in model.q_L:
        model.q_L[index].value = data_areas['q_L'][index]

    # # Warm-start from previous solution if available
    # if prev_solution is not None:
    #     for var_name, var_values in prev_solution.items():
    #         var = getattr(model, var_name)
    #         for index, val in var_values.items():
    #             var[index].value = val  # Set initial values

    model = pyomo_solve(
        model,
        augmented_obj_function,
        area_name=area_name,
        area_info=area_info,
        shared_vars=shared_vars,
        dual_vars=dual_vars,
        rho=rho,
        obj_fcn=obj_fcn,
    )
    solutions = store_results(model)
    original_objective_value = value(model.original_obj)  # Convert Pyomo expression to numerical value

    augmented_objective_value = value(model.augmented_obj)  # Assuming 'obj' is the name of the objective

    solutions['original_objective'] = original_objective_value
    solutions['augmented_objective'] = augmented_objective_value
    return area_name, solutions

def augmented_obj_function(model, **kwargs):
    area_name = model.area_name
    area_info = model.area_info
    shared_vars = model.shared_vars
    dual_vars = model.dual_vars
    rho = model.rho
    obj_fcn = model.obj_fcn

    original_obj  = obj_fcn(model)

    f = original_obj

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

                x_p = model.P_subs[tt,ph]
                x_q = model.Q_subs[tt,ph]
                x_v = [model.v[tt, i, ph] for i in model.Nset if i == local_node_id]

                f += (
                        dual_p[t][ph_idx] * (x_p - shared_p[t][ph_idx]) +
                        dual_q[t][ph_idx] * (x_q - shared_q[t][ph_idx]) +
                        dual_v[t][ph_idx] * (x_v - shared_v[t][ph_idx]) +
                        (rho / 2) * (
                                (x_p - shared_p[t][ph_idx]) ** 2 +
                                (x_q - shared_q[t][ph_idx]) ** 2 +
                                (x_v - shared_v[t][ph_idx]) ** 2
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

                x_p = [model.P[tt, (i, k), ph] for (i, k) in model.Lset if k == local_node_id]
                x_q = [model.Q[tt, (i, k), ph] for (i, k) in model.Lset if k == local_node_id]
                x_v = [model.v[tt, i, ph] for i in model.Nset if i == local_node_id]

                f += (
                        dual_p[t][ph_idx] * (x_p - shared_p[t][ph_idx]) +
                        dual_q[t][ph_idx] * (x_q - shared_q[t][ph_idx]) +
                        dual_v[t][ph_idx] * (x_v - shared_v[t][ph_idx]) +
                        (rho / 2) * (
                                (x_p - shared_p[t][ph_idx]) ** 2 +
                                (x_q - shared_q[t][ph_idx]) ** 2 +
                                (x_v - shared_v[t][ph_idx]) **2
                        )
                )
    # Update the objective function with dual and penalty expressions
    augmented_obj = f

    model.original_obj = original_obj
    model.augmented_obj = augmented_obj

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

def compute_locals(area_info, area_results):
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
            v_key = f"{area}_{conn_area}_v"
            p_local[p_key] = np.vstack([area_p[key] for key in area_p
                                        if key[1][0] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1][0] == local_node]).reshape((-1, 3))
            v_local[v_key] = np.vstack([area_v[key] for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))

        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            p_key = f"{area}_{conn_area}_p"
            q_key = f"{area}_{conn_area}_q"
            v_key = f"{area}_{conn_area}_v"
            p_local[p_key] = np.vstack([area_p[key] for key in area_p
                                        if key[1][1] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1][1] == local_node]).reshape((-1, 3))
            v_local[v_key] = np.vstack([area_v[key] for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))
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

def update_area_values(area_info,data_by_area,p_global,q_global):
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node_id = area_info[area]['down_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph_idx, ph in enumerate("abc"):
                    data_by_area[area]['p_L'][t,local_node_id,ph] = p_global[f"{conn_area}_{area}_p"][t-1, ph_idx]
                    data_by_area[area]['q_L'][t,local_node_id,ph] = q_global[f"{conn_area}_{area}_q"][t-1, ph_idx]

    return data_by_area

def update_lagrange(area_info,dual_vars,p_local,q_local,v_local,p_global,q_global,v_global,rho):
    lagrange_update = {}
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            p_diff = p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"]
            q_diff = q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"]
            v_diff = v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"]

            lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_diff)
            lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_diff)
            lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_diff)
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            p_diff = p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"]
            q_diff = q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"]
            v_diff = v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"]

            lagrange_update[f"lambda_{area}_{conn_area}_p"] = dual_vars[f"lambda_{area}_{conn_area}_p"][-1] + rho * (p_diff)
            lagrange_update[f"lambda_{area}_{conn_area}_q"] = dual_vars[f"lambda_{area}_{conn_area}_q"][-1] + rho * (q_diff)
            lagrange_update[f"lambda_{area}_{conn_area}_v"] = dual_vars[f"lambda_{area}_{conn_area}_v"][-1] + rho * (v_diff)

    return lagrange_update

def share_global_dual(area_info,shared_vars,dual_vars,lagrange_update,p_global,q_global,v_global):
    for area in area_info.keys():
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"])
            shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"])
            shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"])
            dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"])
            dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"])
            dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"])
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"].append(p_global[f"{area}_{conn_area}_p"])
            shared_vars[f"{area}_{conn_area}_q"].append(q_global[f"{area}_{conn_area}_q"])
            shared_vars[f"{area}_{conn_area}_v"].append(v_global[f"{area}_{conn_area}_v"])
            dual_vars[f"lambda_{area}_{conn_area}_p"].append(lagrange_update[f"lambda_{area}_{conn_area}_p"])
            dual_vars[f"lambda_{area}_{conn_area}_q"].append(lagrange_update[f"lambda_{area}_{conn_area}_q"])
            dual_vars[f"lambda_{area}_{conn_area}_v"].append(lagrange_update[f"lambda_{area}_{conn_area}_v"])

    return shared_vars,dual_vars

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
        if vars in ['P', 'Q', 'v']:
            filtered_dictionaries[vars] = {}  # Initialize an empty dictionary for each `vars`
            for key, value in dopfVals[vars].items():
                key1 = key[1]
                if isinstance(key1, tuple) and any(isinstance(sub, str) for sub in key1):
                    continue
                if isinstance(key1, str):
                    continue
                filtered_dictionaries[vars][key] = value
        else:
            # For all other variables, simply copy them over
            filtered_dictionaries[vars] = dopfVals[vars]
    return filtered_dictionaries

def solve_ADMM(data, data_by_area, area_info,obj_fcn, rho, max_iterations):
    shared_vars, dual_vars = initialize_shared_dual(area_info, data)
    mu = 10
    tau = 2
    convergence = {}
    objective = {}
    aug_objective = {}
    areas = list(area_info.keys())
    with mp.Pool(processes=len(areas), initializer=init_worker) as pool:
        for iter in range(max_iterations):
            # Solve all areas in parallel
            results = pool.starmap(process_area,
                                   [(data_by_area[area], area, area_info, shared_vars, dual_vars, rho, obj_fcn)
                                    for area in areas])
            area_results = {a: s for a, s in results}


            p_local, q_local, v_local = compute_locals(area_info, area_results)

            p_global, q_global, v_global = compute_globals(area_info, p_local, q_local, v_local)

            data_by_area = update_area_values(area_info,data_by_area,p_global,q_global)

            lagrange_update = update_lagrange(area_info, dual_vars, p_local, q_local, v_local, p_global, q_global, v_global,rho)

            shared_vars, dual_vars = share_global_dual(area_info, shared_vars, dual_vars, lagrange_update, p_global, q_global, v_global)

            # ## Convergence Check
            # primal_residual = {}
            # dual_residual = {}
            #
            # for area in areas:
            #     primal_residual[area] = [] # Initialize a list to store the max differences for the area
            #     dual_residual[area] = []
            #
            #     # Iterate over down_areas
            #     for conn_area in area_info[area]['down_areas']:
            #         dual_residual[area].append(max(
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_p"][-1] - shared_vars[f"{area}_{conn_area}_p"][-2]) ** 2)),
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_q"][-1] - shared_vars[f"{area}_{conn_area}_q"][-2]) ** 2)),
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_v"][-1] - shared_vars[f"{area}_{conn_area}_v"][-2]) ** 2))
            #         ))
            #         primal_residual[area].append(max(
            #             np.max(np.linalg.norm(p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"]) ** 2),
            #             np.max(np.linalg.norm(q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"]) ** 2),
            #             np.max(np.linalg.norm(v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"]) ** 2)
            #         ))
            #
            #     # Iterate over up_area
            #     for conn_area in area_info[area]['up_area']:
            #         dual_residual[area].append(max(
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_p"][-1] - shared_vars[f"{area}_{conn_area}_p"][-2]) ** 2)),
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_q"][-1] - shared_vars[f"{area}_{conn_area}_q"][-2]) ** 2)),
            #             np.max(rho * (np.linalg.norm(shared_vars[f"{area}_{conn_area}_v"][-1] - shared_vars[f"{area}_{conn_area}_v"][-2]) ** 2))
            #         ))
            #         primal_residual[area].append(max(
            #             np.max(np.linalg.norm(p_local[f"{area}_{conn_area}_p"] - p_global[f"{area}_{conn_area}_p"]) ** 2),
            #             np.max(np.linalg.norm(q_local[f"{area}_{conn_area}_q"] - q_global[f"{area}_{conn_area}_q"]) ** 2),
            #             np.max(np.linalg.norm(v_local[f"{area}_{conn_area}_v"] - v_global[f"{area}_{conn_area}_v"]) ** 2)
            #         ))
            # # Print statement for debugging
            # max_primal = np.max([np.max(sublist) for sublist in primal_residual.values()])
            # max_dual = np.max([np.max(sublist) for sublist in dual_residual.values()])
            # tol = max(max_primal,max_dual)

            ## Convergence Check
            max_shared_diff = 0
            for shared_list in shared_vars.values():
                if len(shared_list) >= 2:
                    diff = np.max(rho * np.linalg.norm(shared_list[-1] - shared_list[-2]) ** 2)
                    max_shared_diff = max(max_shared_diff, diff)
            max_dual_diff = 0
            for dual_list in dual_vars.values():
                if len(dual_list) >= 2:
                    diff = np.max(np.linalg.norm(dual_list[-1] - dual_list[-2]) ** 2)
                    max_dual_diff = max(max_dual_diff, diff)
            tol = max(max_shared_diff,max_dual_diff)
            convergence[iter] = tol
            if obj_fcn == cost_minimize:
                objective[iter] = area_results['area1']['objective_value']
                aug_objective[iter] = area_results['area1']['augmented_objective']
            else:
                objective[iter] = sum([area_results[area]['objective_value'] for area in areas])
                aug_objective[iter] = sum(area_results[area]['augmented_objective'] for area in areas)

            print(f"iteration = {iter}, tolerance={tol}, objective value: {objective[iter]},original obj:{objective[iter]}, augmented obj = {aug_objective[iter]}")
            if tol < 1e-7:
                print(f"Converged after {iter} iterations")
                print(f"total objective value for DOPF:{objective[iter]}")
                break

            # # Adaptive ρ adjustment
            # if iter > 0:
            #     if max_shared_diff > mu * max_dual_diff:
            #         rho *= tau
            #         print(f"Increased ρ to {rho:.2e}")
            #     elif max_dual_diff > mu * max_shared_diff:
            #         rho /= tau
            #         print(f"Decreased ρ to {rho:.2e}")

    dopf = arrange_solution_by_areas(area_info, area_results)

    dopfVals = merge_solutions(dopf)
    dopfVals = exclude_dummies(dopfVals)

    return dopfVals,objective,aug_objective,convergence
