from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize, power_flow, cost_minimize_with_scd
from Build_Model.store import store_results

def solve_copf(data, obj,solver='gurobi',non_linear=False, p_control=False, integer=False):
    model = build_pyomo_model(data, obj, stage_idx=None, non_linear=non_linear, p_control=p_control, integer=integer)
    pyomo_solve(model, obj_func=obj,solver=solver)
    results = store_results(model)
    return results