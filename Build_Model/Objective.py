from pyomo.environ import Objective, minimize, value, SolverFactory,SolverStatus,TerminationCondition,Var,NonNegativeReals,inequality,Constraint

RED = '\033[91m'
GREEN = '\033[92m'
RESET = '\033[0m'
def voltage_deviation_minimize_with_scd(model, **kwargs):
    ## variable for voltage deviation
    model.z = Var(model.Tset, model.bus_phase_set, domain=NonNegativeReals)

    def voltage_deviation_rule_lower(model,t,j,ph):
        return -model.z[t,j,ph]<=model.v[t,j,ph]-1

    model.voltage_deviation_lower_constraint = Constraint(model.Tset, model.bus_phase_set, rule=voltage_deviation_rule_lower)

    def voltage_deviation_rule_upper(model,t,j,ph):
        return model.v[t,j,ph]-1 <= model.z[t,j,ph]

    model.voltage_deviation_upper_constraint = Constraint(model.Tset, model.bus_phase_set, rule=voltage_deviation_rule_upper)

    deviation = sum(model.z[t, j, ph] for t in model.Tset for j, ph in model.bus_phase_set)

    # Add SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                        (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                        for t in model.Tset for j in model.Bset)
        return deviation + alpha_scd * scd_terms

    return deviation

def substation_power_minimize(model):
    # Sum over substation phases only
    return sum(model.P_subs[t, j, ph] for t in model.Tset for j, ph in model.substation_phase_set)

def power_flow_with_scd(model, **kwargs):
    # SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                        (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                        for t in model.Tset for j in model.Bset)
        return alpha_scd * scd_terms

    return 0

def power_flow(model, **kwargs):
    return 0

def loss_minimize(model, **kwargs):
    r = model.r
    return sum(
        r[ph + ph][i, j] * (model.P[t, i, j, ph]**2 + model.Q[t, i, j, ph]**2)
        for t in model.Tset for i, j, ph in model.branch_phase_set)

def loss_minimize_with_scd(model, **kwargs):
    r = model.r

    # Calculate total loss (same for both linear and non-linear)
    total_loss = sum(
        r[ph + ph][i, j] * (model.P[t, i, j, ph]**2 + model.Q[t, i, j, ph]**2)
        for t in model.Tset for i, j, ph in model.branch_phase_set)

    # SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 20)
        scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                       (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                       for t in model.Tset for j in model.Bset)
        return total_loss + alpha_scd * scd_terms

    return total_loss

def cost_minimize(model, **kwargs):
    cost = model.cost
    # Compute total substation power for each time period
    Psubs = {t: sum(model.P_subs[t, j, ph] for j, ph in model.substation_phase_set) for t in model.Tset}
    return sum(Psubs[t] * cost[t] for t in model.Tset)

def cost_minimize_with_scd(model, **kwargs):
    cost = model.cost

    # Compute total substation power for each time period
    Psubs = {t: sum(model.P_subs[t, j, ph] for j, ph in model.substation_phase_set) for t in model.Tset}
    total_cost = sum(Psubs[t] * cost[t] for t in model.Tset)

    # SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                        (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                        for t in model.Tset for j in model.Bset)
        return total_cost + alpha_scd * scd_terms

    return total_cost

def pyomo_solve(model, obj_func,**kwargs):
    # Store kwargs as attributes on the model
    for key, value in kwargs.items():
        setattr(model, key, value)
    if hasattr(model, 'obj'):
        model.del_component('obj')  # Remove old objective

    model.obj = Objective(rule=obj_func, sense=minimize)
    solver = getattr(model, "solver", 'gurobi')
    opt = SolverFactory(solver)
    if solver == 'ipopt':
        opt.options['linear_solver'] = 'ma97'  # Use HSL MA97 for linear solves
    # opt.options['tol'] = 1e-6  # loosen from default 1e-8
    # opt.options['dual_inf_tol'] = 1e-4  # loosen dual tolerance
    # opt.options['constr_viol_tol'] = 1e-6
    # opt.options['acceptable_tol'] = 1e-4  # accept near-optimal solution
    # opt.options['max_iter'] = 1000
    # opt.options['nlp_scaling_method'] = 'gradient-based'
    # opt.options['mu_strategy'] = 'adaptive'
    # opt.set_options('NonConvex=2')  # Allow non-convex problems
    # opt.options['tol'] = 1e-6  # Set tolerance
    # opt.options['max_iter'] = 10000  # Set max iterations
    # opt.options['print_level'] = 5  # Set print level
    # opt = SolverFactory('scip', executable=r"C:\Program Files\SCIPOptSuite 9.2.0\bin\scip.exe")
    results = opt.solve(model, tee=False)
    if results.solver.status == "ok" and results.solver.termination_condition == "optimal":
        print(f"{GREEN}Solver completed successfully.{RESET}")
    else:
        print(f"{RED}Solver failed: {results.solver.termination_condition}.{RESET}")

        # Save IIS to file
        # model.write("model.ilp", format="lp")


    return model