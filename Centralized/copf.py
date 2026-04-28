import math
import numpy as np
import gurobipy as gp
from pyomo.environ import (value, SolverFactory, Constraint)
from Centralized.isocp import _solve_isocp
from Build_Model.Constraints import build_pyomo_model,get_or_build_model
from Build_Model.Objective    import pyomo_solve, cost_minimize, loss_minimize, power_flow, cost_minimize_with_scd
from Build_Model.store        import store_results


def solve_copf(
    data,
    obj,
    stage_idx=None,
    solver: str = "gurobi",
    alpha_scd: float = 1e-3,
    non_linear: bool = False,
    isocp: bool = False,
    p_control: bool = False,
    integer: bool = False,
    single_battery_variable: bool = False,
    gamma: float = 0.5,
    inner_tol: float = 1e-4,
    gap_tol: float = 1e-4,
    max_inner: int = 50,
) -> dict:

    model = get_or_build_model(data,obj,stage_idx=None,non_linear=non_linear,isocp=isocp,p_control=p_control,integer=integer,single_battery_variable=single_battery_variable)
    pyomo_solve(model, obj_func=obj, solver=solver, alpha_scd=alpha_scd)
    sol = store_results(model)

    if isocp:
        ## Solving Linear model
        print(f"Entering ISOCP iteration")

        socp_model = _solve_isocp(
            prev_sol=sol, model=model,
            solver=solver,
            gamma=gamma,
            inner_tol=inner_tol,
            gap_tol=gap_tol,
            max_inner=max_inner,
        )
        sol = store_results(socp_model)

    return sol