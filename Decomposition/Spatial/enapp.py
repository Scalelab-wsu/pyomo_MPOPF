from Build_Model.Constraints import build_pyomo_model,get_or_build_model
from Build_Model.Objective import pyomo_solve,cost_minimize_with_scd,loss_minimize_with_scd
from Build_Model.store import store_results
import numpy as np
import multiprocessing as mp
from collections import defaultdict,ChainMap
from Centralized.isocp import _solve_isocp,reset_isocp_cuts

# Worker initialization function
# def init_worker():
#     global _model_cache
#     _model_cache = {}

# _model_cache = {}

def process_area(data_areas, area_name, obj_fcn, solver,alpha_scd=1e-3,prev_solution=None, non_linear=False,isocp=False, p_control=False, integer=False,single_battery_variable=False):

    data_areas['v_max'] = {key:1.1 for key in data_areas['v_max'].keys()}
    model = get_or_build_model(data_areas, obj_fcn, stage_idx=None, area_name=area_name,non_linear=non_linear, isocp=isocp, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)

    # Parameter updates remain the same
    for index in model.p_L:
        model.p_L[index].value = data_areas['p_L'][index]
    for index in model.q_L:
        model.q_L[index].value = data_areas['q_L'][index]
    for index in model.v_swing:
        model.v_swing[index].value = data_areas['v_swing'][index]

    # # Warm-start from previous solution if available
    # if prev_solution is not None:
    #     for var_name, var_values in prev_solution.items():
    #         var = getattr(model, var_name)
    #         for index, value in var_values.items():
    #             var[index].value = value  # Set initial values

    reset_isocp_cuts(model)
    model = pyomo_solve(model,obj_fcn,solver=solver,alpha_scd=alpha_scd)
    solutions = store_results(model)
    if isocp:
        socp_model = _solve_isocp(prev_sol=solutions, model=model,solver=solver,gamma=0.5,inner_tol=1e-3,gap_tol=1e-3)
        solutions = store_results(socp_model)
        return area_name,solutions
    return area_name, solutions


def initialize_shared(area_info, data):
    shared_vars = {}
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
                                        if key[1] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1] == local_node]).reshape((-1, 3))
            ## alpha sharing
            p_local[p_key] = (1 - alpha)*p_local[p_key] + alpha * shared_vars[p_key][-1]
            q_local[q_key] = (1 - alpha) * q_local[q_key] + alpha * shared_vars[q_key][-1]
        # Downstream connections
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            v_key = f"{area}_{conn_area}_v"
            v_local[v_key] = np.vstack([np.sqrt(area_v[key]) for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))
            ## alpha sharing
            v_local[v_key] = (1 - alpha) * v_local[v_key] + alpha * shared_vars[v_key][-1]
    return p_local, q_local, v_local

def update_area_values(area_info, data_by_area, p_local, q_local, v_local):
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


def share_local(area_info, shared_vars, p_local, q_local, v_local):
    for area in area_info.keys():
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_v"].append(v_local[f"{area}_{conn_area}_v"])
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"].append(p_local[f"{area}_{conn_area}_p"])
            shared_vars[f"{area}_{conn_area}_q"].append(q_local[f"{area}_{conn_area}_q"])
    return shared_vars


def arrange_solution_by_areas(area_info, area_results):
    # Remap local node IDs to global IDs
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            global_node = area_info[conn_area]['up_global_node_id'][0]

            for var_type in ['P', 'Q']:
                updated = {}
                for (t, i, k, ph), val in area_results[area][var_type].items():
                    if k == local_node:
                        updated[(t, i, global_node, ph)] = val
                    else:
                        updated[(t, i, k, ph)] = val
                area_results[area][var_type] = updated

    # Collect all solutions
    dopf = defaultdict(dict)
    for area, results in area_results.items():
        for var_name, values in results.items():
            dopf[var_name][area] = values
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

def solve_EnAPP(data, data_by_area, area_info, obj_fcn, *,solver, alpha_scd=1e-3,max_iterations=50, alpha=0, non_linear=False, isocp=False,p_control=False, integer=False,single_battery_variable=False):
    shared_vars = initialize_shared(area_info, data)
    convergence = {}
    objective = {}
    areas = list(area_info.keys())

    # # Parallel Processing
    # with mp.Pool(processes=len(areas), initializer=init_worker) as pool:
    #     for iter in range(max_iterations):
    #         # Solve all areas in parallel (flags threaded through)
    #         results = pool.starmap(
    #             process_area,
    #             [
    #                 (data_by_area[area], area, obj_fcn,solver,alpha_scd, None, non_linear,isocp, p_control, integer,single_battery_variable)
    #                 for area in areas
    #             ],
    #         )
    #         area_results = {a: s for a, s in results}
    #
    #         # Compute boundary variables
    #         p_local, q_local, v_local = compute_locals(area_info, area_results,shared_vars,alpha)
    #
    #         # Update area data with neighbor values
    #         data_by_area = update_area_values(area_info, data_by_area,
    #                                           p_local, q_local, v_local)
    #
    #         # Update shared variables
    #         shared_vars = share_local(area_info, shared_vars,
    #                                   p_local, q_local, v_local)
    #
    #         # Check convergence
    #         max_diff = 0
    #         for var_list in shared_vars.values():
    #             if len(var_list) >= 2:
    #                 diff = np.max(np.abs(var_list[-1] - var_list[-2]))
    #                 max_diff = max(max_diff, diff)
    #         tol = max_diff
    #         convergence[iter] = tol
    #
    #         if obj_fcn == cost_minimize_with_scd:
    #             objective[iter] = area_results['area1']['objective_value']
    #         else:
    #             objective[iter] = sum(area_results[a]['objective_value'] for a in areas)
    #
    #         print(f"Iter {iter}: Tol={tol}, Obj={objective[iter]}")
    #         if tol < 1e-4:
    #             break
    #         alpha = alpha/2

    for iteration in range(max_iterations):
        # isocp= iteration>=1
        results = [process_area(data_by_area[area], area, obj_fcn,solver,alpha_scd, None, non_linear,isocp, p_control, integer,single_battery_variable) for area in areas]
        area_results = {a: s for a, s in results}

        # Compute boundary variables
        p_local, q_local, v_local = compute_locals(area_info, area_results,shared_vars,alpha)

        # Update area data with neighbor values
        data_by_area = update_area_values(area_info, data_by_area,
                                          p_local, q_local, v_local)

        # Update shared variables
        shared_vars = share_local(area_info, shared_vars,
                                  p_local, q_local, v_local)

        # Check convergence
        max_diff = 0
        for var_list in shared_vars.values():
            if len(var_list) >= 2:
                diff = np.max(np.abs(var_list[-1] - var_list[-2]))
                max_diff = max(max_diff, diff)
        tol = max_diff
        convergence[iteration] = tol

        if obj_fcn == cost_minimize_with_scd:
            objective[iteration] = area_results['area1']['objective_value']
        else:
            objective[iteration] = sum(area_results[a]['objective_value'] for a in areas)

        print(f"Iteration {iteration}: Tol={tol}, Obj={objective[iteration]}")
        if tol < 1e-4:
            break
        alpha = alpha/2

    # Final processing
    dopf = arrange_solution_by_areas(area_info, area_results)
    dopfVals = merge_solutions(dopf)
    dopfVals = exclude_dummies(dopfVals)
    return dopfVals, objective, convergence