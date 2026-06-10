
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve,cost_minimize_with_scd,loss_minimize_with_scd
from Build_Model.store import store_results
import numpy as np
import multiprocessing as mp
from collections import defaultdict,ChainMap
from pyomo.environ import value

# Worker initialization function
def init_worker():
    global _model_cache
    _model_cache = {}

def process_area(data_areas,area_name,area_info, shared_vars, dual_vars, rho,obj_fcn,solver,alpha_scd=1e-3,prev_solution = None, non_linear=False, p_control=False, integer=False,single_battery_variable=False):
    global _model_cache
    # Cache models by (area, formulation) so toggling flags builds the right model
    cache_key = (area_name, bool(non_linear), bool(p_control), bool(integer))

    if cache_key not in _model_cache:
        data_areas['v_max'] = {key: 1.1 for key in data_areas['v_max'].keys()}
        model = build_pyomo_model(data_areas,obj_fcn,stage_idx=None, non_linear=non_linear, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)
        _model_cache[cache_key] = model
    else:
        model = _model_cache[cache_key]
    if 'area1' not in cache_key:
        model.substation_voltage_magnitude.deactivate()

    # Parameter updates remain the same
    for index in model.p_L:
        model.p_L[index].value = data_areas['p_L'][index]
    for index in model.q_L:
        model.q_L[index].value = data_areas['q_L'][index]

    model = pyomo_solve(
        model,
        augmented_obj_function,
        solver=solver,
        alpha_scd=alpha_scd,
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

                x_p = [model.P_subs[tt,i,ph] for i in model.Nset if i == local_node_id]
                x_q = [model.Q_subs[tt,i,ph] for i in model.Nset if i == local_node_id]
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

                x_p = [model.P[tt, i, k, ph] for (i, k) in model.Lset if k == local_node_id]
                x_q = [model.Q[tt, i, k, ph] for (i, k) in model.Lset if k == local_node_id]
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
                                        if key[1] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1] == local_node]).reshape((-1, 3))
            v_local[v_key] = np.vstack([area_v[key] for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))

        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            p_key = f"{area}_{conn_area}_p"
            q_key = f"{area}_{conn_area}_q"
            v_key = f"{area}_{conn_area}_v"
            p_local[p_key] = np.vstack([area_p[key] for key in area_p
                                        if key[2] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[2] == local_node]).reshape((-1, 3))
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
                    for (t, i, k, ph), val in value.items():
                        if k == local_node_id:
                            updated_dict[(t, i, global_node_id, ph)] = val
                        else:
                            updated_dict[(t, i, k, ph)] = val
                    area_results[area][key] = updated_dict

    dopf = defaultdict(dict)
    for area_name, vars_dict in area_results.items():
        for key, value in vars_dict.items():
            dopf[key][area_name] = value

    return dopf

def merge_solutions(dopf):
    merged = {
        'P_subs': dopf['P_subs']['area1'],
        'Q_subs': dopf['Q_subs']['area1'],
        'P': dict(ChainMap(*[dopf['P'][a] for a in dopf['P']])),
        'Q': dict(ChainMap(*[dopf['Q'][a] for a in dopf['Q']])),
        'v': dict(ChainMap(*[dopf['v'][a] for a in dopf['v']])),
        'p_D': dict(ChainMap(*[dopf['p_D'][a] for a in dopf['p_D']])),
        'q_D': dict(ChainMap(*[dopf['q_D'][a] for a in dopf['q_D']])),
        'P_c': dict(ChainMap(*[dopf['P_c'][a] for a in dopf['P_c']])),
        'P_d': dict(ChainMap(*[dopf['P_d'][a] for a in dopf['P_d']])),
        'B': dict(ChainMap(*[dopf['B'][a] for a in dopf['B']])),
    }
    return merged


def exclude_dummies(dopfVals):
    def _is_dummy_key(key):
        # For P/Q: keys are (t, from_bus, to_bus, ph)
        # For v: keys are (t, bus, ph)
        return isinstance(key, tuple) and any(isinstance(x, str) and x.startswith('D') for x in key)

    filtered = {}
    for var, dct in dopfVals.items():
        if var in ['P', 'Q', 'v']:
            filtered[var] = {k: v for k, v in dct.items() if not _is_dummy_key(k)}
        else:
            filtered[var] = dct
    return filtered

def solve_ADMM(data, data_by_area, area_info,obj_fcn, *,solver,alpha_scd,rho, max_iterations,non_linear=False, p_control=False, integer=False,single_battery_variable=False):
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
                                   [(data_by_area[area], area, area_info, shared_vars, dual_vars, rho, obj_fcn,solver,alpha_scd,None, non_linear, p_control, integer, single_battery_variable)
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
            if obj_fcn == cost_minimize_with_scd:
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
