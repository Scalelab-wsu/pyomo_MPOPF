import math
import tempfile
import os
from pyomo.environ import ConcreteModel, Var, Param,Constraint, ConstraintList, Set, NonNegativeReals, Reals, minimize, sqrt, inequality, Binary, sin, cos,Objective,minimize,Suffix,SolverFactory
from pyomo.contrib import appsi
MODEL_CACHE = {}
SOLVER_CACHE = {}

def _make_cache_key(stage_idx,area_name, non_linear, isocp,p_control, integer,
                    single_battery_variable) -> tuple:
    return (stage_idx,
        area_name if area_name is not None else None,
        bool(non_linear), bool(isocp),bool(p_control), bool(integer),
        bool(single_battery_variable),
    )


def get_or_build_model(
    data, obj,solver="gurobi",alpha_scd=1e-3,stage_idx=None,area_name=None,
    non_linear=False,isocp=False, p_control=False, integer=False,
    single_battery_variable=False,
):
    global MODEL_CACHE, SOLVER_CACHE
    key = _make_cache_key(stage_idx, area_name, non_linear,isocp, p_control,
                          integer, single_battery_variable)

    if key not in MODEL_CACHE:
        model = build_pyomo_model(
            data, obj, alpha_scd=alpha_scd,stage_idx=stage_idx,
            non_linear=non_linear, isocp=isocp,
            p_control=p_control, integer=integer,
            single_battery_variable=single_battery_variable,
        )

        MODEL_CACHE[key] = model
        if solver == "gurobi":
            s = appsi.solvers.Gurobi()
            s.config.stream_solver = False
            s.config.load_solution = True
            # s._solver_options['QCPDual'] = 1
            # s._solver_options['NonConvex'] = 2
            # s.update_config.check_for_new_or_removed_constraints = False
            # s.update_config.check_for_new_or_removed_vars = False
            # s.update_config.check_for_new_or_removed_params = False
            # s.update_config.check_for_new_objective = False
            # # # s.update_config.update_constraints = False
            # s.update_config.update_vars = False
            # s.update_config.update_named_expressions = False
            # s.update_config.update_objective = False
            # s.update_config.treat_fixed_vars_as_params = False
            s._solver_options['OutputFlag'] = 0
            SOLVER_CACHE[key] = s
        if solver == "ipopt":
            s = appsi.solvers.Ipopt()
            s.config.stream_solver = False ## SAME AS  model_tee = False
            # s._solver_options['linear_solver'] = 'pardiso'
            _ipopt_ws = tempfile.mkdtemp(prefix="pyomo_appsi_ipopt_")
            s.config.filename = os.path.join(_ipopt_ws, "ipopt")
            SOLVER_CACHE[key] = s

        SOLVER_CACHE[key].set_instance(model)
        SOLVER_CACHE[key].config.load_solution = True

    return MODEL_CACHE[key],SOLVER_CACHE[key]

def build_pyomo_model(data, obj, alpha_scd=1e-3,stage_idx = None, non_linear=False, isocp=False,p_control=False, integer=False,single_battery_variable=False):
    model = ConcreteModel()
    # model.dual = Suffix(direction=Suffix.IMPORT)

    # Sets
    if stage_idx is None:
        local_Tset = list(data['Tset'])
    elif isinstance(stage_idx, tuple):
        ws, we = stage_idx
        local_Tset = list(range(ws, we+1))
    else:
        model.theta = Var(domain=NonNegativeReals)
        local_Tset = Set(initialize=[stage_idx])

    model.Tset = local_Tset
    model.alpha_scd = alpha_scd
    tmin_local = min(local_Tset)
    tmax_local = max(local_Tset)  # last timestep of this model's Tset
    tmax_horizon = 24
    tmin_horizon = 1

    model.tmin_local = tmin_local
    model.tmax_local = tmax_local  # last timestep of this model's Tset
    model.tmax_horizon = tmax_horizon
    model.tmin_horizon = tmin_horizon

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
    model.branch_phase_pair_set = Set(initialize=[((i, j), p, q) for (i, j) in model.Lset for p in branch_phases[(i, j)] for q in branch_phases[(i, j)]])
    model.gen_phase_set = Set(initialize=[(j, ph) for j in model.Dset for ph in gen_phases[j]])
    model.bat_phase_set = Set(initialize=[(j, ph) for j in model.Bset for ph in bat_phases[j]])
    model.substation_phase_set = Set(initialize=[(j, ph) for j in model.substationBus for ph in bus_phases[j]])

    ## initializing model parameters
    model.r = data['r']
    model.x = data['x']
    # THRESHOLD = 1e-6
    # for key in model.r:
    #     for branch in model.r[key]:
    #         if abs(model.r[key][branch]) < THRESHOLD:
    #             model.r[key][branch] = 0.0
    # for key in model.x:
    #     for branch in model.x[key]:
    #         if abs(model.x[key][branch]) < THRESHOLD:
    #             model.x[key][branch] = 0.0

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
        model.p_D = Var(model.Tset, model.gen_phase_set, domain=NonNegativeReals,initialize=0)
        model.q_D = Var(model.Tset, model.gen_phase_set, domain=NonNegativeReals)
    else:
        model.p_D = Param(model.Tset, model.gen_phase_set, initialize=lambda m, t, j, ph: data['p_D'][(t, j, ph)])
        model.q_D = Var(model.Tset, model.gen_phase_set,initialize=0)

    if single_battery_variable:
            model.P_b = Var(model.Tset, model.Bset, domain=Reals,initialize=0)
    else:
        model.P_c = Var(model.Tset, model.Bset, domain=NonNegativeReals, initialize=0)
        model.P_d = Var(model.Tset, model.Bset, domain=NonNegativeReals, initialize=0)

    model.P_subs = Var(model.Tset, model.substation_phase_set, domain=NonNegativeReals,initialize=0)
    model.Q_subs = Var(model.Tset, model.substation_phase_set, domain=NonNegativeReals,initialize=0)
    model.P = Var(model.Tset, model.branch_phase_set,initialize=0)
    model.Q = Var(model.Tset, model.branch_phase_set,initialize=0)
    model.v = Var(model.Tset, model.bus_phase_set, domain=NonNegativeReals,initialize=1)
    model.B = Var(model.Tset, model.Bset, domain=NonNegativeReals,initialize=0)

    if non_linear:
        # Current angle parameter
        model.l = Var(model.Tset, model.branch_phase_pair_set, domain=NonNegativeReals,initialize=0)
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

    if isocp:
        # Current angle parameter
        model.l = Var(model.Tset, model.branch_phase_pair_set, domain=NonNegativeReals,initialize=0)
        def delta_init(m, t, i, j, ph):
            return data['I_ang'][t, i, j, ph]

        model.delta = Param(model.Tset, model.branch_phase_set, initialize=delta_init,mutable=True)
        # Power, Voltage and Current Constraint (only for phases present in branch)
        def power_voltage_current_socp_rule(model, t, i, j, ph):
            Pij = model.P[t, i, j, ph]
            Qij = model.Q[t, i, j, ph]
            vi = model.v[t, i, ph]
            lij = model.l[t, i, j, ph, ph]
            return Pij ** 2 + Qij ** 2 - vi * lij <= 0

        model.power_voltage_current_socp = Constraint(model.Tset, model.branch_phase_set, rule=power_voltage_current_socp_rule)

        # Current magnitude cross-product constraint
        def current_magnitude_socp_rule(model, t, i, j, p, q):
            if p == q:
                return Constraint.Skip
            return model.l[t, i, j, p, q] ** 2 - model.l[t, i, j, p, p] * model.l[t, i, j, q, q] <= 0

        model.current_magnitude_socp = Constraint(model.Tset, model.branch_phase_pair_set, rule=current_magnitude_socp_rule)

        # Current magnitude symmetry constraint
        def current_magnitude_symmetry_rule(model, t, i, j, p, q):
            if p == q:
                return Constraint.Skip
            return model.l[t, i, j, p, q]  - model.l[t, i, j, q, p] == 0

        model.current_magnitude_symmetry = Constraint(model.Tset, model.branch_phase_pair_set, rule=current_magnitude_symmetry_rule)

    # Real power balance constraint
    def real_power_balance_rule(model, t, j, ph):
        substationBus = data['substationBus']
        n_j_phases = len(bus_phases[j])
        # Get phases for incoming and outgoing branches at node j
        incoming_pij = 0 if j in substationBus else sum(model.P[t, i, jj, ph] for i, jj in model.Lset if jj == j and ph in branch_phases[(i, jj)])
        outgoing_pij = sum(model.P[t, jj, k, ph] for jj, k in model.Lset if jj == j and ph in branch_phases[(jj, k)])
        P_subs = model.P_subs[t, j, ph] if (j, ph) in model.substation_phase_set else 0
        PD_t = model.p_D[t, j, ph] if (j, ph) in model.gen_phase_set else 0
        p_load = model.p_L[t, j, ph]
        # n_ph = len(bus_phases[j])
        if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
            P_c = model.P_c[t, j]/n_j_phases if j in model.Bset else 0
            P_d = model.P_d[t, j]/n_j_phases if j in model.Bset else 0
            battery_power = P_d - P_c
        elif hasattr(model, 'P_b'):
            battery_power = model.P_b[t, j]/n_j_phases if j in model.Bset else 0

        if non_linear or isocp:
            r = model.r
            x = model.x
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
        if non_linear or isocp:
            r = model.r
            x = model.x
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
        r = model.r
        x = model.x
        br_phases = branch_phases[(i, j)]
        if non_linear or isocp:
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
    if stage_idx is None:
        # Centralized: b0 hardcoded at tmin, pure chain thereafter
        def battery_dynamics_rule(model, t, j):
            prev_soc = data['b0'][j] if t == tmin_horizon else model.B[t - 1, j]
            if single_battery_variable:
                return model.B[t, j] == prev_soc - model.P_b[t, j]
            return (model.B[t, j] == prev_soc+ model.P_c[t, j] * 0.95 - model.P_d[t, j] / 0.95)

    elif isinstance(stage_idx, int):
        # DDDP: single step, prev_B is the only input SOC
        model.prev_B = Param(model.Bset,initialize={b: data['b0'][b] for b in data['Bset']},mutable=True)

        def battery_dynamics_rule(model, t, j):
            if single_battery_variable:
                return model.B[t, j] == model.prev_B[j] - model.P_b[t, j]
            return (model.B[t, j] == model.prev_B[j]+ model.P_c[t, j] * 0.95 - model.P_d[t, j] / 0.95)

    else:
        # OTD window: pure chain. tmin skipped — boundary_soc pins it.
        model.prev_B = Param(model.Bset,initialize={b: data['b0'][b] for b in data['Bset']},mutable=True)
        model.term_dual = Param(model.Bset,initialize={b: 0 for b in data['Bset']},mutable=True)
        model.term_B = Param(model.Bset,initialize={b: data['b0'][b] for b in data['Bset']},mutable=True)
        model.term_Pc = Param(model.Bset,initialize={b: 0 for b in data['Bset']},mutable=True)
        model.term_Pd = Param(model.Bset,initialize={b: 0 for b in data['Bset']},mutable=True)

        def battery_dynamics_rule(model, t, j):
            if t == tmin_horizon:
                prev_soc = data['b0'][j]
            elif t == tmin_local:
                prev_soc = model.prev_B[j]
            else:
                prev_soc = model.B[t - 1, j]
            if single_battery_variable:
                return model.B[t, j] == prev_soc - model.P_b[t, j]
            return model.B[t, j] == prev_soc+ model.P_c[t, j] * 0.95 - (model.P_d[t, j] / 0.95)

    model.battery_dynamics = Constraint(model.Tset, model.Bset, rule=battery_dynamics_rule)

    # Final SOC = initial SOC rule
    def final_soc_rule(model, t, j):
        initial_B = data['b0'][j]
        # If this is a temporal window (stage_idx is tuple), skip final SOC for non-terminal windows
        if isinstance(stage_idx, tuple):
            # Only enforce if this window contains the global final timestep
            ws, we = stage_idx
            if we == tmax_horizon and t == tmax_horizon:
                return model.B[t, j] == initial_B
            else:
                return Constraint.Skip
        else:
            # For centralized or DDDP, apply normally
            if t == tmax_horizon:
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
        if single_battery_variable:
            def battery_power_rule(model, t, j):
                Pmax = data['p_B'][j]
                return inequality(-Pmax, model.P_b[t, j], Pmax)

            model.battery_power_limits = Constraint(model.Tset, model.Bset, rule=battery_power_rule)
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
    if isinstance(stage_idx, int):
        model.cuts = ConstraintList()
        model.obj = Objective(expr=model.stage_cost + model.theta, sense=minimize)
    else:
        model.obj = Objective(expr=model.stage_cost, sense=minimize)
    return model


