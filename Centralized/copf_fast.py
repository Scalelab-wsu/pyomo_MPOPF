
import gurobipy as gp
from pyomo.environ import value, SolverFactory, Constraint
from Build_Model.Constraints_delta import build_delta_pyomo_model
from Build_Model.Constraints       import build_pyomo_model
from Build_Model.Objective         import pyomo_solve
from Build_Model.Objective_delta         import pyomo_solve_delta
from Build_Model.store             import store_results


def _extract_solution(model, prev=None):
    sol = {
        'P': {}, 'Q': {}, 'v': {}, 'l': {},
        'P_subs': {}, 'Q_subs': {},
        'q_D': {}, 'p_D': {},
        'B': {}, 'P_b': {}, 'P_c': {}, 'P_d': {},'objective_value' : {}
    }

    is_previous = prev is not None

    for t in model.Tset:
        for (i, j, ph) in model.branch_phase_set:
            if is_previous:
                sol['P'][t, i, j, ph] = value(model.dP[t, i, j, ph]) + prev['P'][t, i, j, ph]
                sol['Q'][t, i, j, ph] = value(model.dQ[t, i, j, ph]) + prev['Q'][t, i, j, ph]
            else:
                sol['P'][t, i, j, ph] = value(model.P[t, i, j, ph])
                sol['Q'][t, i, j, ph] = value(model.Q[t, i, j, ph])

        for (i, j, p, q) in model.branch_phase_pair_set:
            if is_previous:
                sol['l'][t, i, j, p, q] = value(model.dl[t, i, j, p, q]) + prev['l'][t, i, j, p, q]
            else:
                sol['l'][t, i, j, p, q] = value(model.l[t, i, j, p, q])

        for (j, ph) in model.bus_phase_set:
            if is_previous:
                sol['v'][t, j, ph] = value(model.dv[t, j, ph]) + prev['v'][t, j, ph]
            else:
                sol['v'][t, j, ph] = value(model.v[t, j, ph])

        for (j, ph) in model.substation_phase_set:
            if is_previous:
                sol['P_subs'][t, j, ph] = value(model.dP_subs[t, j, ph]) + prev['P_subs'][t, j, ph]
                sol['Q_subs'][t, j, ph] = value(model.dQ_subs[t, j, ph]) + prev['Q_subs'][t, j, ph]
            else:
                sol['P_subs'][t, j, ph] = value(model.P_subs[t, j, ph])
                sol['Q_subs'][t, j, ph] = value(model.Q_subs[t, j, ph])

        for (j, ph) in model.gen_phase_set:
            if is_previous:
                sol['q_D'][t, j, ph] = value(model.dq_D[t, j, ph]) + prev['q_D'][t, j, ph]
            else:
                sol['q_D'][t, j, ph] = value(model.q_D[t, j, ph])

            sol['p_D'][t, j, ph] = value(model.p_D[t, j, ph])

        for j in model.Bset:
            if is_previous:
                sol['B'][t, j] = value(model.dB[t, j]) + prev['B'][t, j]
            else:
                sol['B'][t, j] = value(model.B[t, j])

            if is_previous:
                if hasattr(model, 'dP_b'):
                    sol['P_b'][t, j] = value(model.dP_b[t, j]) + prev['P_b'][t, j]
                else:
                    sol['P_c'][t, j] = value(model.dP_c[t, j]) + prev['P_c'][t, j]
                    sol['P_d'][t, j] = value(model.dP_d[t, j]) + prev['P_d'][t, j]
            else:
                if hasattr(model, 'P_b'):
                    sol['P_b'][t, j] = value(model.P_b[t, j])
                else:
                    sol['P_c'][t, j] = value(model.P_c[t, j])
                    sol['P_d'][t, j] = value(model.P_d[t, j])
    sol['objective_value'] = value(model.obj)

    return sol

def _compute_gaps(model=None, prev=None):
    e_pvc, e_cmc = {}, {}
    lin_pvc, lin_cmc = {}, {}
    is_previous = prev is not None
    is_model = model is not None
    max_gap = 0.0

    if is_model and is_previous:
        for t in model.Tset:
            for (i, j, ph) in model.branch_phase_set:
                P0 = value(model.dP[t, i, j, ph]) + prev['P'][t, i, j, ph]
                Q0 = value(model.dQ[t, i, j, ph]) + prev['Q'][t, i, j, ph]
                v0 = value(model.dv[t, i, ph]) + prev['v'][t, i, ph]
                l0 = value(model.dl[t, i, j, ph, ph]) + prev['l'][t, i, j, ph, ph]

                gap = P0 ** 2 + Q0 ** 2 - v0 * l0
                e_pvc[t, i, j, ph] = gap
                lin_pvc[t, i, j, ph] = (P0, Q0, v0, l0)
                max_gap = max(max_gap, abs(gap))

            for (i, j, p, q) in model.branch_phase_pair_set:
                if p == q:
                    continue

                lpq = value(model.dl[t, i, j, p, q]) + prev['l'][t, i, j, p, q]
                lpp = value(model.dl[t, i, j, p, p]) + prev['l'][t, i, j, p, p]
                lqq = value(model.dl[t, i, j, q, q]) + prev['l'][t, i, j, q, q]

                gap = lpq ** 2 - lpp * lqq
                e_cmc[t, i, j, p, q] = gap
                lin_cmc[t, i, j, p, q] = (lpq, lpp, lqq)
                max_gap = max(max_gap, abs(gap))
    elif is_previous:
            for (t, i, j, ph) in prev['P'].keys():
                P0 = prev['P'][t, i, j, ph]
                Q0 = prev['Q'][t, i, j, ph]
                v0 = prev['v'][t, i, ph]
                l0 = prev['l'][t, i, j, ph, ph]

                gap = P0 ** 2 + Q0 ** 2 - v0 * l0
                e_pvc[t, i, j, ph] = gap
                lin_pvc[t, i, j, ph] = (P0, Q0, v0, l0)
                max_gap = max(max_gap, abs(gap))

            for (t, i, j, p, q) in prev['l'].keys():
                if p == q:
                    continue

                lpq = prev['l'][t, i, j, p, q]
                lpp = prev['l'][t, i, j, p, p]
                lqq = prev['l'][t, i, j, q, q]

                gap = lpq**2 - lpp * lqq
                e_cmc[t, i, j, p, q] = gap
                lin_cmc[t, i, j, p, q] = (lpq, lpp, lqq)
                max_gap = max(max_gap, abs(gap))

    return e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap

def _add_directional_constraints(dm, ds, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma):
    for t in dm.Tset:
        for (i, j, ph) in dm.branch_phase_set:
            P0, Q0, v0, l0 = lin_pvc[t, i, j, ph]
            con = Constraint(expr=(
                2*P0*dm.dP[t,i,j,ph] + 2*Q0*dm.dQ[t,i,j,ph] - l0*dm.dv[t,i,ph] - v0*dm.dl[t,i,j,ph,ph]
                >= (gamma - 1.0) * e_pvc[t, i, j, ph]
            ))
            name = f"dpvc_{t}_{i}_{j}_{ph}"
            dm.add_component(name, con)
            ds.add_constraint(con)

        for (i, j, p, q) in dm.branch_phase_pair_set:
            if p == q:
                continue
            lpq, lpp, lqq = lin_cmc[t, i, j, p, q]
            con = Constraint(expr=(
                2*lpq*dm.dl[t,i,j,p,q] - lqq*dm.dl[t,i,j,p,p] - lpp*dm.dl[t,i,j,q,q]
                >= (gamma - 1.0) * e_cmc[t, i, j, p, q]
            ))
            name = f"dcmc_{t}_{i}_{j}_{p}_{q}"
            dm.add_component(name, con)
            ds.add_constraint(con)


def _solve_isocp(base_model, data, obj, stage_idx, non_linear, p_control,
                 integer, single_battery_variable, gamma, inner_tol, max_inner):

    prev_sol = store_results(base_model)
    e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(prev=prev_sol)
    if abs(max_gap) < inner_tol:
        print("  Initial SOCP relaxation already exact ✓")
        return store_results(base_model)

    from Build_Model.Objective_delta import loss_minimize_with_scd
    obj = loss_minimize_with_scd
    print("Running ISOCP Iterations")
    for k in range(1, max_inner + 1):
        dm = build_delta_pyomo_model(
            data, obj, prev_sol, stage_idx=stage_idx, non_linear=non_linear,
            isocp=True, p_control=p_control, integer=integer,
            single_battery_variable=single_battery_variable,
        )
        ds = SolverFactory("gurobi_persistent")
        ds.set_instance(dm)
        ds.options.update({"OutputFlag": 0, "NonConvex": 2, "BarHomogeneous": 1, "NumericFocus": 3})

        _add_directional_constraints(dm, ds, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma)
        ds.solve(dm, tee=False, save_results=False, warmstart=False)

        if ds._solver_model.Status not in (gp.GRB.OPTIMAL, gp.GRB.SUBOPTIMAL):
            print(f"  [ISOCP k={k}] solve failed — status {ds._solver_model.Status}")
            return prev_sol

        prev_sol = _extract_solution(dm, prev=prev_sol)
        e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(dm, prev=prev_sol)


        pvc_v = list(e_pvc.values())
        cmc_v = list(e_cmc.values()) if e_cmc else [0]
        print(f"  [ISOCP k={k:2d}] obj={value(dm.obj):.6f}  gap={max_gap:.3e} | "
              f"PVC [{min(pvc_v):.3e},{max(pvc_v):.3e}] CMC [{min(cmc_v):.3e},{max(cmc_v):.3e}]")

        if max_gap < inner_tol:
            print(f"  [ISOCP] converged at k={k} ✓")
            return prev_sol

    print(f"  [ISOCP] max_inner={max_inner} reached without convergence")
    return prev_sol


def solve_copf(data, obj, stage_idx=None, solver="gurobi", alpha_scd=1e-3,
               non_linear=False, isocp=False, p_control=False, integer=False,
               single_battery_variable=False, gamma=0.9, inner_tol=1e-4, max_inner=100):

    model = build_pyomo_model(
        data, obj, stage_idx, non_linear=False, isocp=False,
        p_control=p_control, integer=integer, single_battery_variable=single_battery_variable,
    )
    pyomo_solve(model, obj_func=obj, solver=solver, alpha_scd=alpha_scd)

    if not isocp:
        return store_results(model)
    store_results(model)  # Store initial solution for gap computation

    return _solve_isocp(
        model, data=data, obj=obj, stage_idx=stage_idx,
        non_linear=non_linear, p_control=p_control, integer=integer,
        single_battery_variable=single_battery_variable,
        gamma=gamma, inner_tol=inner_tol, max_inner=max_inner,
    )