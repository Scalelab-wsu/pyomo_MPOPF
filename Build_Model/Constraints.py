
from pyomo.environ import ConcreteModel, Var, Constraint, Param, Set, NonNegativeReals, minimize,sqrt,inequality

def build_pyomo_model(data):
    model = ConcreteModel()

    # Sets
    model.Tset = data['Tset']
    model.Nset = data['Nset']
    model.Lset = data['Lset']
    model.Bset = data['Bset']
    model.Dset = data['Dset']
    model.phases = data['phases']

    ## initializing model parameters
    model.r = data['r']
    model.x = data['x']
    default = 100
    model.cost = data['costshape']

    # Variables
    model.P_subs = Var(model.Tset, model.phases, domain=NonNegativeReals,bounds=(0,default))
    model.P = Var(model.Tset, model.Lset, model.phases,bounds=(-default,default))
    model.Q = Var(model.Tset, model.Lset, model.phases,bounds=(-default,default))
    model.v = Var(model.Tset, model.Nset, model.phases, domain=NonNegativeReals)
    model.q_D = Var(model.Tset, model.Dset, model.phases)
    model.P_c = Var(model.Tset, model.Bset, model.phases, domain=NonNegativeReals)
    model.P_d = Var(model.Tset, model.Bset, model.phases, domain=NonNegativeReals)
    model.B = Var(model.Tset, model.Bset, model.phases, domain=NonNegativeReals)

    # Real power balance constraint
    def real_power_balance_rule(model, t, j, ph):
        substationBus = data['substationBus']
        loadshape = data['loadshape']
        pvshape = data['pvshape']
        p_L = data['p_L']
        p_D = data['p_D']
        incoming_pij = (0 if j in substationBus else sum(model.P[t, (i, j), ph] for (i, jj) in model.Lset if jj == j)
)
        outgoing_pij = sum(model.P[t, (j, k), ph] for (jj, k) in model.Lset if jj == j)
        Pc_t = model.P_c[t, j, ph] if j in model.Bset else 0
        Pd_t = model.P_d[t, j, ph] if j in model.Bset else 0
        # PD_t = p_D[(j,ph)] * pvshape[t] if j in model.Dset else 0
        PD_t = p_D[t, j, ph] if j in model.Dset else 0
        # load = p_L[(j, ph)] * loadshape[t]
        load = p_L[(t,j,ph)]

        if j in substationBus:
            return model.P_subs[t, ph] - outgoing_pij - load - Pc_t + PD_t + Pd_t == 0
        else:
            return incoming_pij - outgoing_pij - load - Pc_t + PD_t + Pd_t == 0

    model.real_power_balance = Constraint(model.Tset, model.Nset, model.phases, rule=real_power_balance_rule)

    # Reactive power balance constraint
    def reactive_power_balance_rule(model, t, j, ph):
        substationBus = data['substationBus']
        q_L = data['q_L']
        incoming_qij = (0 if j in substationBus else sum(model.Q[t, i, j, ph] for (i, jj) in model.Lset if jj == j))
        outgoing_qij = sum(model.Q[t, (j, k), ph] for (jj, k) in model.Lset if jj == j)
        load = q_L[(j, ph)]
        q_D_t = model.q_D[t,j,ph] if j in model.Dset else 0
        if j in substationBus:
            return Constraint.Skip
        else:
            return incoming_qij - outgoing_qij - load + q_D_t == 0

    model.reactive_power_balance = Constraint(model.Tset, model.Nset, model.phases, rule=reactive_power_balance_rule)

    def kvl_three_phase_rule(model, t, i, j, ph):
        r = data['r']
        x = data['x']
        if ph == 'a':
            return (model.v[t, j, 'a'] == model.v[t, i, 'a'] -
                    2 * (r['aa'][i, j] * model.P[t, i, j, 'a'] + x['aa'][i, j] * model.Q[t, i, j, 'a']) +
                    (r['ab'][i, j] - sqrt(3) * x['ab'][i, j]) * model.P[t, i, j, 'b'] +
                    (x['ab'][i, j] + sqrt(3) * r['ab'][i, j]) * model.Q[t, i, j, 'b'] +
                    (r['ac'][i, j] + sqrt(3) * x['ac'][i, j]) * model.P[t, i, j, 'c'] +
                    (x['ac'][i, j] - sqrt(3) * r['ac'][i, j]) * model.Q[t, i, j, 'c']
                    )
        elif ph == 'b':
            return (model.v[t, j, 'b'] == model.v[t, i, 'b'] -
                    2 * (r['bb'][i, j] * model.P[t, i, j, 'b'] + x['bb'][i, j] * model.Q[t, i, j, 'b']) +
                    (r['ab'][i, j] + sqrt(3) * x['ab'][i, j]) * model.P[t, i, j, 'a'] +
                    (x['ab'][i, j] - sqrt(3) * r['ab'][i, j]) * model.Q[t, i, j, 'a'] +
                    (r['bc'][i, j] - sqrt(3) * x['bc'][i, j]) * model.P[t, i, j, 'c'] +
                    (x['bc'][i, j] + sqrt(3) * r['bc'][i, j]) * model.Q[t, i, j, 'c']
                    )
        elif ph == 'c':
            return (model.v[t, j, 'c'] == model.v[t, i, 'c'] -
                    2 * (r['cc'][i, j] * model.P[t, i, j, 'c'] + x['cc'][i, j] * model.Q[t, i, j, 'c']) +
                    (r['ac'][i, j] - sqrt(3) * x['ac'][i, j]) * model.P[t, i, j, 'a'] +
                    (x['ac'][i, j] + sqrt(3) * r['ac'][i, j]) * model.Q[t, i, j, 'a'] +
                    (r['bc'][i, j] + sqrt(3) * x['bc'][i, j]) * model.P[t, i, j, 'b'] +
                    (x['bc'][i, j] - sqrt(3) * r['bc'][i, j]) * model.Q[t, i, j, 'b']
                    )
        else:
            return Constraint.Skip

    # Apply the constraint
    model.kvl_three_phase = Constraint(model.Tset, model.Lset, model.phases, rule=kvl_three_phase_rule)

    # Voltage magnitude constraint
    def voltage_magnitude_rule(model, t, j, ph):
        substationBus = data['substationBus']
        swing_voltage = data['v_swing']
        v_min_sq = data['v_min'][j] ** 2
        v_max_sq = data['v_max'][j] ** 2
        if j in substationBus:
            return model.v[t, j, ph] ==  swing_voltage[j,ph] ** 2
        else:
            return inequality(v_min_sq, model.v[t, j, ph] ,v_max_sq)

    model.voltage_magnitude = Constraint(model.Tset, model.Nset, model.phases, rule=voltage_magnitude_rule)

    # Battery dynamics constraint
    def battery_dynamics_rule(model, t, j, ph):
        b0 = data['b0'][j,ph]
        if t == 1:
            return model.B[t, j, ph] == b0 + model.P_c[t, j, ph] * data['eta_c'][(j, ph)] - model.P_d[t, j, ph] / data['eta_d'][(j, ph)]
        else:
            return model.B[t, j, ph] == model.B[t - 1, j, ph] + (model.P_c[t, j, ph] * data['eta_c'][(j, ph)]) - (model.P_d[t, j, ph] / data['eta_d'][(j, ph)])

    model.battery_dynamics = Constraint(model.Tset, model.Bset, model.phases, rule=battery_dynamics_rule)

    # Battery charge/discharge power limits
    def battery_limits_rule(model, t, j, ph):
        bmin = data['bmin'][j,ph]
        bmax = data['bmax'][j,ph]
        return inequality(bmin, model.B[t, j, ph] ,bmax)

    model.battery_limits = Constraint(model.Tset, model.Bset, model.phases, rule=battery_limits_rule)

    # Battery charging power limit
    def charging_power_rule(model, t, j, ph):
        Pmax = data['p_B'][j,ph]
        return model.P_c[t,j,ph] <= Pmax

    model.charging_power_limits = Constraint(model.Tset, model.Bset, model.phases, rule=charging_power_rule)

    # Battery discharging power limit
    def discharging_power_rule(model, t, j, ph):
        Pmax = data['p_B'][j, ph]
        return model.P_d[t, j, ph] <= Pmax

    model.discharging_power_limits = Constraint(model.Tset, model.Bset, model.phases, rule=discharging_power_rule)

    # DER reactive power limit
    def der_reactive_power_rule(model, t, j, ph):
        pvshape = data['pvshape']
        # P = data['p_D'][j,ph] * pvshape[t]
        P = data['p_D'][(t,j,ph)]
        S = data['s_D'][j,ph]
        q_max = ((S ** 2 - P ** 2) ** (1/2))
        q_min = -q_max
        return inequality(q_min, model.q_D[t, j, ph] ,q_max)

    model.der_reactive_power_limits = Constraint(model.Tset, model.Dset, model.phases, rule=der_reactive_power_rule)

    return model

