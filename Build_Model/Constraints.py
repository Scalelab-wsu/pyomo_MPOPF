import math
from pyomo.environ import ConcreteModel, Var, Param,Constraint, ConstraintList, Set, NonNegativeReals, Reals, minimize, sqrt, inequality, Binary, sin, cos,Objective,minimize,Suffix

def build_pyomo_model(data, obj, stage_idx = None, non_linear=False, p_control=False, integer=False):
    model = ConcreteModel()
    model.dual = Suffix(direction=Suffix.IMPORT)

    # Sets
    if stage_idx is not None:
        model.theta = Var(domain=NonNegativeReals)
        model.Tset = Set(initialize=[stage_idx])
    else:
        model.Tset = data['Tset']
    model.times = Set(initialize=list(data['Tset']))
    tmax = max(data['Tset'])
    model.Nset = data['Nset']
    model.Lset = data['Lset']
    model.Bset = data['Bset']
    model.Dset = data['Dset']
    model.phases = data['phases']
    model.substationBus = data['substationBus']

    # Phase-aware sets
    bus_phases = data['bus_phases']
    branch_phases = data['branch_phases']
    gen_phases = data['gen_phases']
    bat_phases = data['bat_phases']

    # Store phase info on model for later access
    model.bus_phases = bus_phases
    model.branch_phases = branch_phases
    model.gen_phases = gen_phases
    model.bat_phases = bat_phases

    # Create indexed sets for only existing phases
    model.bus_phase_set = Set(initialize=[(j, ph) for j in model.Nset for ph in bus_phases[j]])
    model.branch_phase_set = Set(initialize=[((i, j), ph) for (i, j) in model.Lset for ph in branch_phases[(i, j)]])
    model.gen_phase_set = Set(initialize=[(j, ph) for j in model.Dset for ph in gen_phases[j]])
    model.bat_phase_set = Set(initialize=[(j, ph) for j in model.Bset for ph in bat_phases[j]])
    model.substation_phase_set = Set(initialize=[(j, ph) for j in model.substationBus for ph in bus_phases[j]])

    ## initializing model parameters
    model.r = data['r']
    model.x = data['x']
    model.cost = data['costshape']
    model.eta_c = data['eta_c']
    model.eta_d = data['eta_d']
    model.p_B = data['p_B']
    model.T = data['T']
    model.p_L = Param(model.Tset, model.bus_phase_set, initialize=lambda m, t, j, ph: data['p_L'][(t, j, ph)], mutable=True)
    model.q_L = Param(model.Tset, model.bus_phase_set, initialize=lambda m, t, j, ph: data['q_L'][(t, j, ph)], mutable=True)
    model.v_swing = Param(model.Tset, model.substation_phase_set, initialize=lambda m, t, j, ph: data['v_swing'][(t, j, ph)], mutable=True)
    model.v_max = Param(model.Nset, initialize=data['v_max'], mutable=True)
    model.s_D = Param(model.gen_phase_set, initialize=lambda m, j, ph:data['s_D'][(j,ph)])

    # Variables - defined ONLY for existing phases
    if p_control:
        model.p_D = Var(model.Tset, model.gen_phase_set, domain=NonNegativeReals)
        model.q_D = Var(model.Tset, model.gen_phase_set, domain=NonNegativeReals, bounds=(0, 0))
    else:
        model.p_D = Param(model.Tset, model.gen_phase_set, initialize=lambda m, t, j, ph: data['p_D'][(t, j, ph)])
        model.q_D = Var(model.Tset, model.gen_phase_set)

    model.P_subs = Var(model.Tset, model.substation_phase_set, domain=NonNegativeReals,initialize=0)
    model.Q_subs = Var(model.Tset, model.substation_phase_set, domain=NonNegativeReals,initialize=0)
    model.P = Var(model.Tset, model.branch_phase_set,initialize=0)
    model.Q = Var(model.Tset, model.branch_phase_set,initialize=0)
    model.v = Var(model.Tset, model.bus_phase_set, domain=NonNegativeReals,initialize=1)
    model.B = Var(model.Tset, model.Bset, domain=NonNegativeReals,initialize=0)
    model.P_c = Var(model.Tset, model.Bset, domain=NonNegativeReals,initialize=0)
    model.P_d = Var(model.Tset, model.Bset, domain=NonNegativeReals,initialize=0)

    if non_linear:
        # Current angle parameter
        model.branch_phase_pair_set = Set(initialize=[((i, j), p, q) for (i, j) in model.Lset for p in branch_phases[(i, j)] for q in branch_phases[(i, j)]])
        model.l = Var(model.Tset, model.branch_phase_pair_set, domain=NonNegativeReals)
        def delta_init(m, t, i, j, ph):
            return data['I_ang'][t, i, j, ph]

        model.delta = Param(model.Tset, model.branch_phase_set, initialize=delta_init)
        # Power, Voltage and Current Constraint (only for phases present in branch)
        def power_voltage_current_rule(model, t, i, j, ph):
            Pij = model.P[t, i, j, ph]
            Qij = model.Q[t, i, j, ph]
            vi = model.v[t, i, ph]
            lij = model.l[t, i, j, ph, ph]
            return Pij ** 2 + Qij ** 2 - vi * lij == 0

        model.power_voltage_current = Constraint(model.Tset, model.branch_phase_set, rule=power_voltage_current_rule)

        # Current magnitude cross-product constraint
        def current_magnitude_rule(model, t, i, j, p, q):
            if p == q:
                return Constraint.Skip
            return model.l[t, i, j, p, q] ** 2 - model.l[t, i, j, p, p] * model.l[t, i, j, q, q] == 0

        model.current_magnitude = Constraint(model.Tset, model.branch_phase_pair_set, rule=current_magnitude_rule)

    # Real power balance constraint
    def real_power_balance_rule(model, t, j, ph):
        substationBus = data['substationBus']
        # Get phases for incoming and outgoing branches at node j
        incoming_pij = 0 if j in substationBus else sum(model.P[t, i, jj, ph] for i, jj in model.Lset if jj == j and ph in branch_phases[(i, jj)])
        outgoing_pij = sum(model.P[t, jj, k, ph] for jj, k in model.Lset if jj == j and ph in branch_phases[(jj, k)])
        P_subs = model.P_subs[t, j, ph] if (j, ph) in model.substation_phase_set else 0
        PD_t = model.p_D[t, j, ph] if (j, ph) in model.gen_phase_set else 0
        p_load = model.p_L[t, j, ph]
        P_c = model.P_c[t, j]/3 if j in model.Bset else 0
        P_d = model.P_d[t, j]/3 if j in model.Bset else 0
        battery_power = P_d - P_c

        if non_linear:
            r = data['r']
            x = data['x']
            loss_term = sum(
                (r[f'{ph}{q}'][i, jj] * cos(model.delta[t, i, jj, ph] - model.delta[t, i, jj, q])
                 + x[f'{ph}{q}'][i, jj] * sin(model.delta[t, i, jj, ph] - model.delta[t, i, jj, q]))
                * model.l[t, i, jj, ph, q]
                for i, jj in model.Lset if jj == j and ph in branch_phases[(i, jj)]
                for q in branch_phases[(i, jj)]
            )
        else:
            loss_term = 0
        if j in substationBus:
            return P_subs - outgoing_pij - p_load + battery_power + PD_t - loss_term == 0
        else:
            return incoming_pij - outgoing_pij - p_load + battery_power + PD_t - loss_term == 0

    model.real_power_balance = Constraint(model.Tset, model.bus_phase_set, rule=real_power_balance_rule)

    # Reactive power balance constraint
    def reactive_power_balance_rule(model, t, j, ph):
        substationBus = data['substationBus']
        incoming_qij = 0 if j in substationBus else sum(model.Q[t, i, jj, ph] for i, jj in model.Lset if jj == j and ph in branch_phases[(i, jj)])
        outgoing_qij = sum(model.Q[t, jj, k, ph] for jj, k in model.Lset if jj == j and ph in branch_phases[(jj, k)])

        Q_subs = model.Q_subs[t, j, ph] if (j, ph) in model.substation_phase_set else 0
        q_load = model.q_L[t, j, ph]
        q_D_t = model.q_D[t, j, ph] if (j, ph) in model.gen_phase_set else 0

        # Loss term: sum over incoming branches and their phase pairs
        if non_linear:
            r = data['r']
            x = data['x']
            loss_term = sum(
                (x[f'{ph}{q}'][i, jj] * cos(model.delta[t, i, jj, ph] - model.delta[t, i, jj, q])
                 - r[f'{ph}{q}'][i, jj] * sin(model.delta[t, i, jj, ph] - model.delta[t, i, jj, q]))
                * model.l[t, i, jj, ph, q]
                for i, jj in model.Lset if jj == j and ph in branch_phases[(i, jj)]
                for q in branch_phases[(i, jj)]
            )
        else:
            loss_term = 0  # No loss term in linear model

        if j in substationBus:
            return Q_subs - outgoing_qij - q_load + q_D_t - loss_term == 0
        else:
            return incoming_qij - outgoing_qij - q_load + q_D_t - loss_term == 0

    model.reactive_power_balance = Constraint(model.Tset, model.bus_phase_set, rule=reactive_power_balance_rule)

    # KVL constraint (three-phase aware)
    def kvl_three_phase_rule(model, t, i, j, ph):
        r = data['r']
        x = data['x']
        br_phases = branch_phases[(i, j)]
        if non_linear:
            loss_term = sum(
                ((r[f'{ph}{q1}'][i, j] * r[f'{ph}{q2}'][i, j] + x[f'{ph}{q1}'][i, j] * x[f'{ph}{q2}'][i, j]) *
                 cos(model.delta[t, i, j, q1] - model.delta[t, i, j, q2]) +
                 (r[f'{ph}{q1}'][i, j] * x[f'{ph}{q2}'][i, j] - x[f'{ph}{q1}'][i, j] * r[f'{ph}{q2}'][i, j]) *
                 sin(model.delta[t, i, j, q1] - model.delta[t, i, j, q2]))
                * model.l[t, i, j, q1, q2]
                for q1 in br_phases
                for q2 in br_phases
            )
        else:
            loss_term = 0

        expr = model.v[t, j, ph] - model.v[t, i, ph] + 2 * (r[f'{ph}{ph}'][i, j] * model.P[t, i, j, ph] + x[f'{ph}{ph}'][i, j] * model.Q[t, i, j, ph])
        if ph == 'a':
            if 'b' in br_phases:
                expr += (- r['ab'][i, j] + sqrt(3) * x['ab'][i, j]) * model.P[t, i, j, 'b'] + \
                        (- x['ab'][i, j] - sqrt(3) * r['ab'][i, j]) * model.Q[t, i, j, 'b']
            if 'c' in br_phases:
                expr += (- r['ac'][i, j] - sqrt(3) * x['ac'][i, j]) * model.P[t, i, j, 'c'] + \
                        (- x['ac'][i, j] + sqrt(3) * r['ac'][i, j]) * model.Q[t, i, j, 'c']
            return expr - loss_term == 0

        elif ph == 'b':
            if 'a' in br_phases:
                expr += (- r['ab'][i, j] - sqrt(3) * x['ab'][i, j]) * model.P[t, i, j, 'a'] + \
                        (- x['ab'][i, j] + sqrt(3) * r['ab'][i, j]) * model.Q[t, i, j, 'a']
            if 'c' in br_phases:
                expr += (- r['bc'][i, j] + sqrt(3) * x['bc'][i, j]) * model.P[t, i, j, 'c'] + \
                        (- x['bc'][i, j] - sqrt(3) * r['bc'][i, j]) * model.Q[t, i, j, 'c']
            return expr - loss_term == 0
        elif ph == 'c':
            if 'a' in br_phases:
                expr += (- r['ac'][i, j] + sqrt(3) * x['ac'][i, j]) * model.P[t, i, j, 'a'] + \
                        (- x['ac'][i, j] - sqrt(3) * r['ac'][i, j]) * model.Q[t, i, j, 'a']
            if 'b' in br_phases:
                expr += (- r['bc'][i, j] - sqrt(3) * x['bc'][i, j]) * model.P[t, i, j, 'b'] + \
                        (- x['bc'][i, j] + sqrt(3) * r['bc'][i, j]) * model.Q[t, i, j, 'b']
            return expr - loss_term == 0
        else:
            return Constraint.Skip

    model.kvl_three_phase = Constraint(model.Tset, model.branch_phase_set, rule=kvl_three_phase_rule)

    # Voltage magnitude limits constraint
    def voltage_magnitude_rule(model, t, j, ph):
        v_min_sq = data['v_min'][j] ** 2
        v_max_sq = model.v_max[j] ** 2
        return inequality(v_min_sq, model.v[t, j, ph], v_max_sq)

    model.voltage_magnitude = Constraint(model.Tset, model.bus_phase_set, rule=voltage_magnitude_rule)

    # Substation voltage magnitude constraint
    def substation_voltage_magnitude_rule(model, t, j, ph):
        swing_voltage = model.v_swing
        return model.v[t, j, ph] == swing_voltage[t, j, ph] ** 2

    model.substation_voltage_magnitude = Constraint(model.Tset, model.substation_phase_set, rule=substation_voltage_magnitude_rule)

    # Battery dynamics constraint
    if stage_idx is not None:
        model.prev_B = Param(model.Bset, initialize={b: data['b0'][b] for b in data['Bset']}, mutable=True)
        def battery_dynamics_rule(model, t, j):
            n_c = 0.95
            n_d = 0.95
            if n_d == 0:
                return model.B[t, j] == model.prev_B[j] + model.P_c[t, j] * n_c
            else:
                return model.B[t, j] == model.prev_B[j] + (model.P_c[t, j] * n_c) - (model.P_d[t, j] / n_d)

        model.battery_dynamics = Constraint(model.Tset, model.Bset, rule=battery_dynamics_rule)
    else:
        def battery_dynamics_rule(model, t, j):
            b0 = data['b0'][j]
            prev_soc = b0 if t == min(data['Tset']) else model.B[t - 1, j]
            n_c = 0.95
            n_d = 0.95
            if n_d == 0:
                return model.B[t, j] == prev_soc + (model.P_c[t, j] * n_c)
            else:
                return model.B[t, j] == prev_soc + (model.P_c[t, j] * n_c) - (model.P_d[t, j] / n_d)

        model.battery_dynamics = Constraint(model.Tset, model.Bset, rule=battery_dynamics_rule)

    # Final SOC = initial SOC rule
    def final_soc_rule(model, t, j):
        initial_B = data['b0'][j]
        if t == tmax:
            return model.B[t, j] == initial_B
        else:
            return Constraint.Skip

    model.final_soc = Constraint(model.Tset, model.Bset, rule=final_soc_rule)

    # Battery charge/discharge power limits
    def battery_limits_rule(model, t, j):
        bmin = data['bmin'][j]
        bmax = data['bmax'][j]
        return inequality(bmin, model.B[t, j], bmax)

    model.battery_limits = Constraint(model.Tset, model.Bset, rule=battery_limits_rule)

    if integer:
        model.u = Var(model.Tset, model.Bset, domain=Binary)

        def charging_power_rule(model, t, j):
            Pmax = data['p_B'][j]
            u = model.u[t, j]
            return model.P_c[t, j] <= (1 - u) * Pmax

        model.charging_power_limits = Constraint(model.Tset, model.Bset, rule=charging_power_rule)

        # Battery discharging power limit
        def discharging_power_rule(model, t, j):
            Pmax = data['p_B'][j]
            u = model.u[t, j]
            return model.P_d[t, j] <= u * Pmax

        model.discharging_power_limits = Constraint(model.Tset, model.Bset, rule=discharging_power_rule)
    else:
        def charging_power_rule(model, t, j):
            Pmax = data['p_B'][j]
            return model.P_c[t, j] <= Pmax

        model.charging_power_limits = Constraint(model.Tset, model.Bset, rule=charging_power_rule)

        # Battery discharging power limit
        def discharging_power_rule(model, t, j):
            Pmax = data['p_B'][j]
            return model.P_d[t, j] <= Pmax

        model.discharging_power_limits = Constraint(model.Tset, model.Bset, rule=discharging_power_rule)

    if p_control:
        # PV active power limit rule
        def der_active_power_rule(model, t, j, ph):
            Prated = data['p_D'][t, j, ph]
            return model.p_D[t, j, ph] <= Prated

        model.der_active_power_limits = Constraint(model.Tset, model.gen_phase_set, rule=der_active_power_rule)
    else:
        # DER reactive power limit
        def der_reactive_power_rule(model, t, j, ph):
            P = data['p_D'][t, j, ph]
            S = data['s_D'][j, ph]
            q_max = sqrt(S ** 2 - P ** 2)
            q_min = -q_max
            return inequality(q_min, model.q_D[t, j, ph], q_max)

        model.der_reactive_power_limits = Constraint(model.Tset, model.gen_phase_set, rule=der_reactive_power_rule)

    model.stage_cost = obj(model) if callable(obj) else obj
    if stage_idx is not None:
        model.cuts = ConstraintList()
        model.obj = Objective(expr=model.stage_cost + model.theta, sense=minimize)
    else:
        model.obj = Objective(expr=model.stage_cost, sense=minimize)
    return model

