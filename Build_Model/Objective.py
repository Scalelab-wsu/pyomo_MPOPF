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

    # Linear SCD for linear model; quadratic SCD for nonlinear or isocp model
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        is_nonlinear = getattr(model, 'non_linear', False)
        is_isocp = getattr(model, 'isocp', False)
        if is_nonlinear or is_isocp:
            scd_terms = sum(model.P_c[t, j]**2 + model.P_d[t, j]**2
                            for t in model.Tset for j in model.Bset)
        else:
            scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                            (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                            for t in model.Tset for j in model.Bset)
        return deviation + alpha_scd * scd_terms

    return deviation

def substation_power_minimize(model):
    # Sum over substation phases only
    return sum(model.P_subs[t, j, ph] for t in model.Tset for j, ph in model.substation_phase_set)

def power_flow_with_scd(model, **kwargs):
    # Linear SCD for linear model; quadratic SCD for nonlinear or isocp model
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        is_nonlinear = getattr(model, 'non_linear', False)
        is_isocp = getattr(model, 'isocp', False)
        if is_nonlinear or is_isocp:
            scd_terms = sum(model.P_c[t, j]**2 + model.P_d[t, j]**2
                            for t in model.Tset for j in model.Bset)
        else:
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

    # Linear SCD for linear model; quadratic SCD for nonlinear or isocp model
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        is_nonlinear = getattr(model, 'non_linear', False)
        is_isocp = getattr(model, 'isocp', False)
        if is_nonlinear or is_isocp:
            scd_terms = sum(model.P_c[t, j]**2 + model.P_d[t, j]**2
                            for t in model.Tset for j in model.Bset)
        else:
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

    # Linear SCD for linear model; quadratic SCD for nonlinear or isocp model
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        alpha_scd = getattr(model, "alpha_scd", 1e-3)
        is_nonlinear = getattr(model, 'non_linear', False)
        is_isocp = getattr(model, 'isocp', False)
        if is_nonlinear :   ## change to is_isocp  if you want to include isocp
            scd_terms = sum(model.P_c[t, j]**2 + model.P_d[t, j]**2
                            for t in model.Tset for j in model.Bset)
        else:
            scd_terms = sum((1 - model.eta_c[j]) * model.P_c[t, j] +
                            (((1 / model.eta_d[j]) - 1) if model.eta_d[j] != 0 else 1.0) * model.P_d[t, j]
                            for t in model.Tset for j in model.Bset)
        total_cost += alpha_scd * scd_terms

    # # SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    # if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
    #     alpha_scd = getattr(model, "alpha_scd", 1e-4)
    #     scd_terms = sum(model.P_c[t, j]**2 +
    #                     model.P_d[t, j]**2
    #                     for t in model.Tset for j in model.Bset)
    #     total_cost +=  alpha_scd * scd_terms

    # # SCD penalty only for linear model (to prevent simultaneous charge/discharge)
    # if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
    #     alpha_scd = getattr(model, "alpha_scd", 1e-4)
    #     scd_terms = sum(model.B[t, j]**2 
    #                     for t in model.Tset for j in model.Bset)
    #     total_cost +=  alpha_scd * scd_terms

    # # Schwarz-OTD coupling penalty (active only on Schwarz OTD windows, which
    # # carry term_dual / term_B Params). Benders-OTD windows skip both blocks.
    if hasattr(model, 'term_dual') and hasattr(model,'term_Pc') and hasattr(model,'term_Pd'):
        t_local = model.tmax_local
        if t_local == model.tmax_horizon:
            penalty_terms = 0
        else:
            penalty_terms = sum(model.term_dual[j] * model.B[t_local, j] for j in model.Bset)
        total_cost += penalty_terms

    # if hasattr(model, 'term_B') and getattr(model, 'isocp', False):
        t_local = model.tmax_local
        if t_local == model.tmax_horizon:
            correction_term = 0
        else:
            rho = model.rho if hasattr(model, 'rho') else 25
            correction_term = rho * sum((model.B[t_local,j] - model.term_B[j])**2 for j in model.Bset)
        total_cost += correction_term

    # ## Regularizer for DDDP
    # rho = 1e-4
    # total_cost += rho * sum((model.B[model.tmax_local,j])**2 for j in model.Bset)
    # ADMM temporal boundary penalties (Pinto et al. 2020, eq. 19 / Fig. 1).
    # Initial-side penalty: skip for window 1 (tmin_local == tmin_horizon uses b0 directly).
    # Terminal-side penalty: coordinator sets admm_rho_out=0 for the last window.
    if hasattr(model, 'admm_rho_in'):
        t_last = model.tmax_local
        rho_in  = model.admm_rho_in
        rho_out = model.admm_rho_out
        if model.tmin_local > model.tmin_horizon:
            total_cost += (rho_in / 2) * sum(
                (model.B_init[j] - model.admm_z_in[j] + model.admm_u_in[j]) ** 2
                for j in model.Bset)
        total_cost += (rho_out / 2) * sum(
            (model.B[t_last, j] - model.admm_z_out[j] + model.admm_u_out[j]) ** 2
            for j in model.Bset)
    return total_cost

def pyomo_solve(model, model_solver,obj_func,**kwargs):
    # Store kwargs as attributes on the model
    for key, value in kwargs.items():
        setattr(model, key, value)
    if hasattr(model, 'obj'):
        model.del_component('obj')  # Remove old objective

    model.obj = Objective(rule=obj_func, sense=minimize)
    solver = getattr(model, "solver", 'highs')
    opt = SolverFactory(solver)
    results = opt.solve(model, tee=True)
    if results.solver.status == "ok" and results.solver.termination_condition == "optimal":
        print(f"{GREEN}Solver completed successfully.{RESET}")
    else:
        print(f"{RED}Solver failed: {results.solver.termination_condition}.{RESET}")

        # Save IIS to file
        # model.write("model.ilp", format="lp")


    return model