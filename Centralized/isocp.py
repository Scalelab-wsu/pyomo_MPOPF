import numpy as np
import gurobipy as gp
from pyomo.environ import (value, Constraint, SolverFactory)
from Build_Model.store import store_results
from pyomo.contrib.appsi.base import TerminationCondition as TC


def initialize_model_variables(model,prev_sol = None):
    prev = prev_sol is not None
    for t in model.Tset:
        for (i, j, ph) in model.branch_phase_set:
            model.P[t, i, j, ph].value = prev_sol['P'][t, i, j, ph] if prev else 0
            model.Q[t, i, j, ph].value = prev_sol['Q'][t, i, j, ph] if prev else 0

        for (i, j, p, q) in model.branch_phase_pair_set:
            model.l[t, i, j, p, q].value = max(0.0,prev_sol['l'][t, i, j, p, q]) if prev else 0

        for (i, ph) in model.bus_phase_set:
            model.v[t, i, ph].value = prev_sol['v'][t, i, ph] if prev else 1

        for (j, ph) in model.substation_phase_set:
            model.P_subs[t, j, ph].value = prev_sol['P_subs'][t, ph] if prev else 0
            model.Q_subs[t, j, ph].value = prev_sol['Q_subs'][t, ph] if prev else 0

        for (j, ph) in model.gen_phase_set:
            if hasattr(model, 'q_D'):
                model.q_D[t, j, ph].value = prev_sol['q_D'][t, j, ph] if prev else 0

        for j in model.Bset:
            if hasattr(model, 'B'):
                model.B[t, j].value = prev_sol['B'][t, j] if prev else 0
            if hasattr(model, 'P_b'):
                model.P_b[t, j].value = prev_sol['P_b'][t, j] if prev else 0
            if hasattr(model, 'P_c'):
                model.P_c[t, j].value = prev_sol['P_c'][t, j] if prev else 0
                model.P_d[t, j].value = prev_sol['P_d'][t, j] if prev else 0

    return model

def apply_trust_region(model, solver, lin_pvc, lin_cmc, rho=0.10, floor=1e-3):
    for (t, i, j, ph), (P0, Q0, v0, lpp0) in lin_pvc.items():
        dP = max(rho * abs(P0),   floor)
        dQ = max(rho * abs(Q0),   floor)
        dL = max(rho * abs(lpp0), floor)
        model.P[t,i,j,ph].setlb(P0 - dP);
        model.P[t,i,j,ph].setub(P0 + dP)
        model.Q[t,i,j,ph].setlb(Q0 - dQ);
        model.Q[t,i,j,ph].setub(Q0 + dQ)
        model.l[t,i,j,ph,ph].setlb(max(0.0,lpp0-dL));
        model.l[t,i,j,ph,ph].setub(lpp0 + dL)
        solver.update_var(model.P[t,i,j,ph])
        solver.update_var(model.Q[t,i,j,ph])
        solver.update_var(model.l[t,i,j,ph,ph])

    # CMC: bound l[p,q] cross-phase currents
    for (t, i, j, p, q), (lpq0, lpp0, lqq0) in lin_cmc.items():
        dlpq = max(rho * abs(lpq0), floor)
        model.l[t,i,j,p,q].setlb(max(0.0, lpq0 - dlpq))
        model.l[t,i,j,p,q].setub(lpq0 + dlpq)
        solver.update_var(model.l[t,i,j,p,q])

    return model, solver

# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------

def _compute_gaps(model):
    '''e_pvc is error of power voltage current (pvc) constraint
    e_cmc is error of current magnitude constraint (cmc)
    lin_pvc is initial linearization point for pvc constraint
    lin_cmc is linearization point for cmc constraint'''
    e_pvc,   e_cmc   = {}, {}
    lin_pvc, lin_cmc = {}, {}
    max_gap = 0.0

    for t in model.Tset:
        for (i, j, ph) in model.branch_phase_set:
            P0   = value(model.P[t, i, j, ph])
            Q0   = value(model.Q[t, i, j, ph])
            v0   = value(model.v[t, i, ph])
            if hasattr(model,'l'):
                lpp0 = value(model.l[t, i, j, ph, ph])
            else:
                lpp0 = (P0 ** 2 + Q0 ** 2)/v0

            gap = P0**2 + Q0**2 - v0 * lpp0
            e_pvc[t, i, j, ph]   = gap
            lin_pvc[t, i, j, ph] = (P0, Q0, v0, lpp0)
            max_gap = max(max_gap, abs(gap))

        for (i, j, p, q) in model.branch_phase_pair_set:
            if p == q:
                continue
            if hasattr(model,'l'):
                lpq0 = value(model.l[t, i, j, p, q])
                lpp0 = value(model.l[t, i, j, p, p])
                lqq0 = value(model.l[t, i, j, q, q])
            else:
                lpp0 = (value(model.P[t, i, j, p]) ** 2 + value(model.Q[t, i, j, p]) ** 2)/value(model.v[t, i, p])
                lqq0 = (value(model.P[t, i, j, q]) ** 2 + value(model.Q[t, i, j, q]) ** 2)/value(model.v[t, i, q])
                lpq0 = np.sqrt(lpp0*lqq0)

            gap = lpq0**2 - lpp0 * lqq0
            e_cmc[t, i, j, p, q]   = gap
            lin_cmc[t, i, j, p, q] = (lpq0, lpp0, lqq0)
            max_gap = max(max_gap, abs(gap))

    return e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap


def _add_linear_directional_constraints_pvc(
        model, dir_pvc, e_pvc, lin_pvc, gamma, gap_tol=1e-4, *, use_persistent: bool = True
):
    for t in model.Tset:
        for (i, j, ph) in model.branch_phase_set:
            key = (t, i, j, ph)
            gap = e_pvc[key]

            if abs(gap) > gap_tol:
                if key in dir_pvc:
                    name, old_con = dir_pvc[key]
                    model.del_component(name)
                    del dir_pvc[key]
                P0, Q0, v0, lpp0 = lin_pvc[key]
                rhs = (gamma + 1) * gap

                new_con = Constraint(expr=(
                        2 * P0 * model.P[t, i, j, ph]
                        + 2 * Q0 * model.Q[t, i, j, ph]
                        - lpp0 * model.v[t, i, ph]
                        - v0 * model.l[t, i, j, ph, ph] >= rhs
                ))

                name = f"dpvc_{t}_{i}_{j}_{ph}"
                model.add_component(name, new_con)
                dir_pvc[key] = (name, new_con)  # Track it

    return model, dir_pvc


def _add_linear_directional_constraints_cmc(
        model, dir_cmc, e_cmc, lin_cmc, gamma, gap_tol=1e-4, *, use_persistent: bool = True
):
    for t in model.Tset:
        for (i, j, p, q) in model.branch_phase_pair_set:
            if p == q:
                continue

            key = (t, i, j, p, q)
            gap = e_cmc[key]

            if abs(gap) > gap_tol:
                if key in dir_cmc:
                    name, old_con = dir_cmc[key]
                    model.del_component(name)
                    del dir_cmc[key]
                lpq0, lpp0, lqq0 = lin_cmc[key]
                rhs = (gamma + 1) * gap

                new_con = Constraint(expr=(
                        2 * lpq0 * model.l[t, i, j, p, q]
                        - lqq0 * model.l[t, i, j, p, p]
                        - lpp0 * model.l[t, i, j, q, q] >= rhs
                ))

                name = f"dcmc_{t}_{i}_{j}_{p}_{q}"
                model.add_component(name, new_con)
                dir_cmc[key] = (name, new_con)

    return model, dir_cmc

def reset_isocp_cuts(model):
    for comp in list(model.component_objects(Constraint, active=True)):
        nm = comp.name
        if not (nm.startswith("dpvc_") or nm.startswith("dcmc_")):
            continue
        model.del_component(comp)

# ---------------------------------------------------------------------------
# ISOCP inner loop
# ---------------------------------------------------------------------------

def _solve_isocp(prev_sol, model,model_solver,gamma=0.9, inner_tol=1e-4, gap_tol=1e-4, max_inner=15):

    e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(model) ## Computing the socp gap
    print(f"Max gap without ISOCP:{max_gap:.3e}")
    if abs(max_gap) < inner_tol:
        print("  Initial SOCP relaxation already exact ✓")
        return model

    dir_pvc = {}
    dir_cmc = {}

    for k in range(max_inner):
        # n_pos_pvc = sum(1 for v in e_pvc.values() if abs(v) > 0.0) ## Finding no. of pvc directional constraints to be added
        # n_pos_cmc = sum(1 for v in e_cmc.values() if abs(v) > 0.0) ## Finding no. of cmc directional constraints to be added
        # print(f"  [ISOCP] adding cuts — PVC: {n_pos_pvc}, CMC: {n_pos_cmc}")

        model, dir_pvc = _add_linear_directional_constraints_pvc(model, dir_pvc, e_pvc, lin_pvc, gamma, gap_tol)
        model, dir_cmc = _add_linear_directional_constraints_cmc(model, dir_cmc, e_cmc, lin_cmc, gamma, gap_tol)

        model = initialize_model_variables(model, prev_sol) ## initializing socp model with previous solution
        # model, model_solver = apply_trust_region(model, model_solver,lin_pvc,lin_cmc,rho=0.1) ## Applying trust region to the current iteration variables
        # model.write("debug_model_socp_first_iter.lp", io_options={'symbolic_solver_labels': True})

        res = model_solver.solve(model)
        tc = getattr(res, 'termination_condition', None)
        if tc != TC.optimal:
            print(f"  [ISOCP] solve failed at iter {k} — termination {tc}")

            return model

        prev_sol = store_results(model)
        e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(model)
        # print(f"  [ISOCP] iter {k:2d}  max_gap={max_gap:.3e}")

        if max_gap < inner_tol:
            print("  [ISOCP] converged ✓")
            return model

    print(f"  [ISOCP] reached max_inner={max_inner} without convergence")
    return model