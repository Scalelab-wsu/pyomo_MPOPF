import pyomo.environ as pyo
from pyomo.contrib import appsi
import numpy as np
from pyomo.common.timing import HierarchicalTimer
import tempfile
import os
m = pyo.ConcreteModel()
m.x = pyo.Var()
m.y = pyo.Var()
m.p = pyo.Param(mutable=True)
m.obj = pyo.Objective(expr=m.x**2 + m.y**2)
m.c1 = pyo.Constraint(expr=m.y >= pyo.exp(m.x))
m.c2 = pyo.Constraint(expr=m.y >= (m.x - m.p)**2)
opt = appsi.solvers.Ipopt()

# Ensure Ipopt writes its .opt and other scratch files to a writable location.
_ipopt_ws = tempfile.mkdtemp(prefix="pyomo_appsi_ipopt_")
opt.config.filename = os.path.join(_ipopt_ws, "ipopt")
timer = HierarchicalTimer()
for p_val in np.linspace(1, 10, 100):
    m.p.value = float(p_val)
    res = opt.solve(m, timer=timer)
    assert res.termination_condition == appsi.base.TerminationCondition.optimal
    print(res.best_feasible_objective)
print(timer)

timer = HierarchicalTimer()
opt.update_config.check_for_new_or_removed_constraints = False
opt.update_config.check_for_new_or_removed_vars = False
opt.update_config.update_constraints = False
opt.update_config.update_vars = False
for p_val in np.linspace(1, 10, 100):
    m.p.value = float(p_val)
    res = opt.solve(m, timer=timer)
    assert res.termination_condition == appsi.base.TerminationCondition.optimal
    print(res.best_feasible_objective)
print(timer)
