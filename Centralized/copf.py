import math
import numpy as np
from pyomo.environ import (value, SolverFactory, Constraint,Objective,minimize)
import time
from Centralized.isocp import _solve_isocp
from Build_Model.Constraints import build_pyomo_model,get_or_build_model
from Build_Model.Objective    import pyomo_solve, cost_minimize, loss_minimize, power_flow, cost_minimize_with_scd
from Build_Model.store        import store_results


def solve_copf(
    data,
    obj,
    stage_idx=None,
    solver: str = "highs",
    alpha_scd: float = 1e-3,
    non_linear: bool = False,
    isocp: bool = False,
    p_control: bool = False,
    integer: bool = False,
    single_battery_variable: bool = False,
    gamma: float = 0.5,
    inner_tol: float = 1e-4,
    gap_tol: float = 1e-4,
    max_inner: int = 20,
) -> dict:
    start_time = time.perf_counter()  # Start timing
    model,model_solver = get_or_build_model(data,obj,solver=solver,alpha_scd=alpha_scd,stage_idx=None,non_linear=non_linear,isocp=isocp,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
    end_time = time.perf_counter()
    # print(f" Centralized Model Built in {end_time - start_time} seconds.")
    # pyomo_solve(model, obj_func=obj, solver=solver, alpha_scd=alpha_scd)
    start_time = time.perf_counter()  # Start timing
    res = model_solver.solve(model)
    tc = getattr(res, 'termination_condition', None)
    if tc is not None and tc.name not in ('optimal', 'locallyOptimal', 'globallyOptimal'):
        raise RuntimeError(f"Centralized solve failed: termination_condition={tc}")
    end_time = time.perf_counter()
    # print(f"Centralized Model Solved in {end_time - start_time} seconds.")
    sol = store_results(model)

    if isocp:
        ## Solving Linear model
        print(f"Entering ISOCP iteration")

        socp_model, gap_history = _solve_isocp(
            prev_sol=sol, model=model, model_solver=model_solver,
            gamma=gamma, inner_tol=inner_tol, gap_tol=gap_tol, max_inner=max_inner,
        )
        sol = store_results(socp_model)
        sol['isocp_gap_history'] = gap_history

    return sol