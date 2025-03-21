from pyomo.environ import Objective, minimize, value, SolverFactory,SolverStatus,TerminationCondition

def substation_power_minimize(model):
    return sum(model.P_subs[t,ph] for t in model.Tset for ph in model.phases)

def power_flow(model, **kwargs):
    return 0

def loss_minimize(model, **kwargs):
    r = model.r
    # Calculate the total losses
    return sum(
        r[ph + ph][i, j] * (model.P[t, (i, j), ph]**2 + model.Q[t, (i, j), ph]**2)
        for t in model.Tset for (i, j) in model.Lset for ph in model.phases
    )

def cost_minimize(model, **kwargs):
    cost = model.cost

    # Compute total substation power for each time period t
    Psubs = {t: sum(model.P_subs[t, ph] for ph in model.phases) for t in model.Tset}
    # Psubs = {t: sum(model.P[t, (i, j), ph] for (i,j) in model.Lset if i in model.substationBus for ph in model.phases) for t in model.Tset}

    # Return the total cost across all time periods
    return sum(Psubs[t] * cost[t] for t in model.Tset)

def pyomo_solve(model, obj_func, **kwargs):
    # Store kwargs as attributes on the model
    for key, value in kwargs.items():
        setattr(model, key, value)

    model.obj = Objective(rule=obj_func, sense=minimize)
    opt = SolverFactory('gurobi')
    # opt.options['logfile'] = 'solver_log.txt'
    # opt.options['IISMethod'] = 2
    # opt = SolverFactory('scip', executable=r"C:\Program Files\SCIPOptSuite 9.2.0\bin\scip.exe")
    results = opt.solve(model, tee=False)
    if results.solver.status == "ok" and results.solver.termination_condition == "optimal":
        print("Solver completed successfully.")
    else:
        print(f"Solver failed: {results.solver.termination_condition}")

        # Save IIS to file
        model.write("model.ilp", format="lp")


    return model