"""
ISOCP-SDDP with persistent solver caching.

Outer loop: model built once per stage, persistent solver keeps it in Gurobi memory.
            SDDP cuts added incrementally via slvr.add_constraint.

Inner loop: directional linearisation constraints added ONCE (first inner iter),
            then only coefficients updated via chgCoeff — no model rebuild ever.
"""

import os, time, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pyomo.environ import value, ConstraintList, SolverFactory
from Build_Model.Constraints import build_pyomo_model

# ── module-level caches ───────────────────────────────────────────────────────
MODEL_CACHE        = {}   # {cache_key: pyomo model}
PERSISTENT_SOLVERS = {}   # {cache_key: persistent solver}
WARM_START_CACHE   = {}   # {stage_idx: {var: {index: value}}}

# Skip directional constraints whose linearisation coefficients are all
# near-zero (zero-flow branch).  All-zero LHS makes Gurobi unbounded (status 4).
_LIN_TOL = 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# Build model + persistent solver once per stage, reuse forever.
# ─────────────────────────────────────────────────────────────────────────────
def get_or_build_stage(stage_idx, data, obj,
                       non_linear=False, p_control=False,
                       integer=False, single_battery_variable=False):
    global MODEL_CACHE, PERSISTENT_SOLVERS
    key = (int(stage_idx), bool(non_linear), bool(p_control),
           bool(integer), bool(single_battery_variable))
    if key not in MODEL_CACHE:
        MODEL_CACHE[key] = build_pyomo_model(
            data, obj, stage_idx,
            non_linear=non_linear, p_control=p_control,
            integer=integer, single_battery_variable=single_battery_variable
        )
        slvr = SolverFactory("gurobi_persistent")
        slvr.set_instance(MODEL_CACHE[key])
        slvr.options['OutputFlag']     = 0
        # slvr.options['Method']         = 2    # barrier
        # slvr.options['BarHomogeneous'] = 1
        # slvr.options['BarConvTol']     = 1e-7
        # slvr.options['NumericFocus']   = 1
        PERSISTENT_SOLVERS[key] = slvr
    return MODEL_CACHE[key], PERSISTENT_SOLVERS[key]


# ─────────────────────────────────────────────────────────────────────────────
# ONE-TIME setup helpers (guarded — safe to call multiple times)
# ─────────────────────────────────────────────────────────────────────────────

def _relax_nonlinear_constraints(m, slvr, t):
    """Replace nonlinear equalities with SOCP inequalities. Runs once."""
    if getattr(m, '_isocp_relaxed', False):
        return
    for con in m.power_voltage_current.values():
        slvr.remove_constraint(con)
    m.power_voltage_current.deactivate()
    for con in m.current_magnitude.values():
        slvr.remove_constraint(con)
    m.current_magnitude.deactivate()

    m.socp_pvc = ConstraintList()
    m.socp_cmc = ConstraintList()
    for i, j, ph in m.branch_phase_set:
        slvr.add_constraint(m.socp_pvc.add(
            m.P[t,i,j,ph]**2 + m.Q[t,i,j,ph]**2 <= m.v[t,i,ph] * m.l[t,i,j,ph,ph]
        ))
    for i, j, p, q in m.branch_phase_pair_set:
        if p != q:
            slvr.add_constraint(m.socp_cmc.add(
                m.l[t,i,j,p,q]**2 <= m.l[t,i,j,p,p] * m.l[t,i,j,q,q]
            ))
    m._isocp_relaxed = True


def _build_var_cache(m, slvr, t):
    """Cache direct Gurobi variable references. Runs once."""
    if hasattr(m, '_grb_var_cache'):
        return
    vm = slvr._pyomo_var_to_solver_var_map
    lpp = {(i,j,ph): vm[id(m.l[t,i,j,ph,ph])] for i,j,ph in m.branch_phase_set}
    lpq = {(i,j,p,q): vm[id(m.l[t,i,j,p,q])]
           for i,j,p,q in m.branch_phase_pair_set if p != q}
    m._grb_var_cache = {
        'P':   {(i,j,ph): vm[id(m.P[t,i,j,ph])] for i,j,ph in m.branch_phase_set},
        'Q':   {(i,j,ph): vm[id(m.Q[t,i,j,ph])] for i,j,ph in m.branch_phase_set},
        'v':   {(i,ph):   vm[id(m.v[t,i,ph])]   for i,ph   in m.bus_phase_set},
        'lpp': lpp,
        'lpq': lpq,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inner loop helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_gaps(m):
    """
    Read .X from cached Gurobi vars (valid right after solve()).
    Returns gaps and linearisation points — both needed for constraint update.
    """
    c = m._grb_var_cache
    e_pvc, e_cmc = {}, {}
    lin_pvc, lin_cmc = {}, {}
    max_gap = 0.0

    for i, j, ph in m.branch_phase_set:
        P0   = c['P'][i,j,ph].X
        Q0   = c['Q'][i,j,ph].X
        v0   = c['v'][i,ph].X
        lpp0 = c['lpp'][i,j,ph].X
        gap  = P0**2 + Q0**2 - v0*lpp0
        e_pvc[i,j,ph]   = gap
        lin_pvc[i,j,ph] = (P0, Q0, v0, lpp0)
        if abs(gap) > max_gap:
            max_gap = abs(gap)

    for i, j, p, q in m.branch_phase_pair_set:
        if p == q:
            continue
        lpq0 = c['lpq'][i,j,p,q].X
        lpp0 = c['lpp'][i,j,p].X
        lqq0 = c['lpp'][i,j,q].X
        gap  = lpq0**2 - lpp0*lqq0
        e_cmc[i,j,p,q]   = gap
        lin_cmc[i,j,p,q] = (lpq0, lpp0, lqq0)
        if abs(gap) > max_gap:
            max_gap = abs(gap)

    return e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap


def _add_dir_constraints(m, slvr, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma):
    """
    ONE-TIME: add directional constraints with real coefficients from current
    solution.  Zero-flow branches (all coefficients < _LIN_TOL) are skipped.
    """
    if getattr(m, '_dir_grb_cons', False):
        return
    grb = slvr._solver_model
    c   = m._grb_var_cache
    pvc, cmc = {}, {}

    for i, j, ph in m.branch_phase_set:
        P0, Q0, v0, lpp0 = lin_pvc[i,j,ph]
        if abs(P0) < _LIN_TOL and abs(Q0) < _LIN_TOL \
                and abs(v0) < _LIN_TOL and abs(lpp0) < _LIN_TOL:
            continue
        e   = e_pvc[i,j,ph]
        rhs = (gamma-1)*e + 2*P0**2 + 2*Q0**2 - 2*lpp0*v0
        pvc[i,j,ph] = grb.addLConstr(
            2*P0*c['P'][i,j,ph] + 2*Q0*c['Q'][i,j,ph]
            - lpp0*c['v'][i,ph] - v0*c['lpp'][i,j,ph] >= rhs,
            name=f"dir_pvc_{i}_{j}_{ph}"
        )

    for i, j, p, q in m.branch_phase_pair_set:
        if p == q:
            continue
        lpq0, lpp0, lqq0 = lin_cmc[i,j,p,q]
        if abs(lpq0) < _LIN_TOL and abs(lpp0) < _LIN_TOL \
                and abs(lqq0) < _LIN_TOL:
            continue
        e   = e_cmc[i,j,p,q]
        rhs = (gamma-1)*e + 2*lpq0**2 - 2*lpp0*lqq0
        cmc[i,j,p,q] = grb.addLConstr(
            2*lpq0*c['lpq'][i,j,p,q] - lqq0*c['lpp'][i,j,p]
            - lpp0*c['lpp'][i,j,q] >= rhs,
            name=f"dir_cmc_{i}_{j}_{p}_{q}"
        )

    grb.update()
    m._dir_grb_cons_pvc = pvc
    m._dir_grb_cons_cmc = cmc
    m._dir_grb_cons     = True


def _update_dir_constraints(m, slvr, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma):
    """
    Update coefficients of existing directional constraints via chgCoeff.
    All .X values come from lin_pvc/lin_cmc (read before any grb.update()).
    ONE grb.update() batches all changes.
    """
    grb = slvr._solver_model
    c   = m._grb_var_cache

    for i, j, ph in m.branch_phase_set:
        con = m._dir_grb_cons_pvc.get((i,j,ph))
        if con is None:
            continue
        P0, Q0, v0, lpp0 = lin_pvc[i,j,ph]
        e   = e_pvc[i,j,ph]
        rhs = (gamma-1)*e + 2*P0**2 + 2*Q0**2 - 2*lpp0*v0
        grb.chgCoeff(con, c['P'][i,j,ph],   2*P0)
        grb.chgCoeff(con, c['Q'][i,j,ph],   2*Q0)
        grb.chgCoeff(con, c['v'][i,ph],    -lpp0)
        grb.chgCoeff(con, c['lpp'][i,j,ph], -v0)
        con.RHS = rhs

    for i, j, p, q in m.branch_phase_pair_set:
        if p == q:
            continue
        con = m._dir_grb_cons_cmc.get((i,j,p,q))
        if con is None:
            continue
        lpq0, lpp0, lqq0 = lin_cmc[i,j,p,q]
        e   = e_cmc[i,j,p,q]
        rhs = (gamma-1)*e + 2*lpq0**2 - 2*lpp0*lqq0
        grb.chgCoeff(con, c['lpq'][i,j,p,q],  2*lpq0)
        grb.chgCoeff(con, c['lpp'][i,j,p],   -lqq0)
        grb.chgCoeff(con, c['lpp'][i,j,q],   -lpp0)
        con.RHS = rhs

    grb.update()


def _apply_warm_start(m, slvr, stage_idx, t):
    """Set PStart from previous solution. Skipped on first outer iteration."""
    if stage_idx not in WARM_START_CACHE:
        return
    ws = WARM_START_CACHE[stage_idx]
    vm = slvr._pyomo_var_to_solver_var_map
    for i, j, ph in m.branch_phase_set:
        vm[id(m.P[t,i,j,ph])].PStart    = ws['P'].get((i,j,ph), 0.0)
        vm[id(m.Q[t,i,j,ph])].PStart    = ws['Q'].get((i,j,ph), 0.0)
        vm[id(m.l[t,i,j,ph,ph])].PStart = ws['l'].get((i,j,ph), 0.0)
    for i, ph in m.bus_phase_set:
        vm[id(m.v[t,i,ph])].PStart = ws['v'].get((i,ph), 1.0)
    slvr._solver_model.update()


def _save_warm_start(m, slvr, stage_idx):
    """Save solution values for next outer iteration. Skipped if no solution."""
    import gurobipy as gp
    if slvr._solver_model.Status not in (gp.GRB.OPTIMAL, gp.GRB.SUBOPTIMAL):
        return
    c = m._grb_var_cache
    WARM_START_CACHE[stage_idx] = {
        'P': {(i,j,ph): c['P'][i,j,ph].X   for i,j,ph in m.branch_phase_set},
        'Q': {(i,j,ph): c['Q'][i,j,ph].X   for i,j,ph in m.branch_phase_set},
        'v': {(i,ph):   c['v'][i,ph].X      for i,ph   in m.bus_phase_set},
        'l': {(i,j,ph): c['lpp'][i,j,ph].X  for i,j,ph in m.branch_phase_set},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main solve function — drop-in replacement for your solve_stage
# ─────────────────────────────────────────────────────────────────────────────
def solve_stage_isocp(stage_idx, prev_stage_B, cuts_future, data, obj,
                      solver,
                      gamma=0.9, inner_tol=1e-4, max_inner=15,
                      alpha_scd=1e-3,
                      non_linear=True, p_control=False,
                      integer=False, single_battery_variable=False):

    m, slvr = get_or_build_stage(
        stage_idx, data, obj,
        non_linear=non_linear, p_control=p_control,
        integer=integer, single_battery_variable=single_battery_variable
    )
    t = stage_idx

    # ── update battery state ──────────────────────────────────────────────
    for j in m.Bset:
        if m.prev_B[j].value != prev_stage_B[j]:
            m.prev_B[j].set_value(prev_stage_B[j])
            slvr.remove_constraint(m.battery_dynamics[t,j])
            slvr.add_constraint(m.battery_dynamics[t,j])

    # ── add new SDDP cuts ─────────────────────────────────────────────────
    current_num_cuts = len(m.cuts)
    for i in range(current_num_cuts, len(cuts_future)):
        alpha, beta = cuts_future[i]
        new_con = m.cuts.add(m.theta >= alpha + sum(beta[j]*m.B[t,j] for j in m.Bset))
        slvr.add_constraint(new_con)

    # ── linear model: plain solve ─────────────────────────────────────────
    if not non_linear or not hasattr(m, 'power_voltage_current'):
        slvr.solve(m, tee=False, save_results=False)
        beta_out = {j: m.dual[m.battery_dynamics[t,j]] for j in m.Bset}
        return value(m.obj), beta_out, {j: value(m.B[t,j]) for j in m.Bset}, value(m.stage_cost)

    # ── ONE-TIME: replace nonlinear equalities with SOCP inequalities ─────
    _relax_nonlinear_constraints(m, slvr, t)

    import gurobipy as gp

    # ── initial SOCP solve ────────────────────────────────────────────────
    _apply_warm_start(m, slvr, stage_idx, t)
    slvr.solve(m, tee=False, save_results=False)
    grb = slvr._solver_model

    if grb.Status not in (gp.GRB.OPTIMAL, gp.GRB.SUBOPTIMAL):
        print(f"  [ISOCP] stage {stage_idx} initial solve status={grb.Status}")
        beta_out = {j: m.dual[m.battery_dynamics[t,j]] for j in m.Bset}
        return value(m.obj), beta_out, {j: value(m.B[t,j]) for j in m.Bset}, value(m.stage_cost)

    # ── ONE-TIME: build Gurobi variable cache ─────────────────────────────
    _build_var_cache(m, slvr, t)

    # ── inner ISOCP loop ──────────────────────────────────────────────────
    for inner_k in range(max_inner):
        # Read .X — valid because last op was solve()
        e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(m)

        if max_gap < inner_tol:
            break

        if inner_k == 0:
            # Add directional constraints with real coefficients (one-time)
            _add_dir_constraints(m, slvr, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma)
        else:
            # Update existing constraint coefficients (no add/remove)
            _update_dir_constraints(m, slvr, e_pvc, e_cmc, lin_pvc, lin_cmc, gamma)

        slvr.solve(m, tee=False, save_results=False)
        if grb.Status not in (gp.GRB.OPTIMAL, gp.GRB.SUBOPTIMAL):
            print(f"  [ISOCP] stage {stage_idx} inner iter {inner_k} status={grb.Status}")
            break

    # ── save warm start for next outer iteration ──────────────────────────
    _save_warm_start(m, slvr, stage_idx)

    beta_out = {j: m.dual[m.battery_dynamics[t,j]] for j in m.Bset}
    return value(m.obj), beta_out, {j: value(m.B[t,j]) for j in m.Bset}, value(m.stage_cost)


# ─────────────────────────────────────────────────────────────────────────────
# Outer SDDP loop
# ─────────────────────────────────────────────────────────────────────────────
def dddp_solve_isocp(data, obj, solver='gurobi', alpha_scd=1e-3,
                     max_iters=50, tol=1e-4,
                     gamma=0.9, inner_tol=1e-4, max_inner=15,
                     non_linear=True, p_control=False,
                     integer=False, single_battery_variable=False):

    global MODEL_CACHE, PERSISTENT_SOLVERS, WARM_START_CACHE
    MODEL_CACHE.clear()
    PERSISTENT_SOLVERS.clear()
    WARM_START_CACHE.clear()

    time_periods = sorted([int(x) for x in list(data['Tset'])])
    num_stages   = len(time_periods)
    Bset         = list(data['Bset'])

    print("Building cached models for all stages...")
    for stage_idx in range(1, num_stages + 1):
        get_or_build_stage(stage_idx, data, obj,
                           non_linear=non_linear, p_control=p_control,
                           integer=integer, single_battery_variable=single_battery_variable)
    print(f"Built {num_stages} cached models.")

    def _solve(stage_idx, prev_B, cuts_list):
        return solve_stage_isocp(
            stage_idx, prev_B, cuts_list, data, obj, solver,
            gamma=gamma, inner_tol=inner_tol, max_inner=max_inner,
            alpha_scd=alpha_scd, non_linear=non_linear,
            p_control=p_control, integer=integer,
            single_battery_variable=single_battery_variable
        )

    cuts         = {f'cuts_{i}': [] for i in range(1, num_stages)}
    initial_b    = data['b0']
    prev_LB      = 0
    LB_container = []
    UB_container = []

    for k in range(1, max_iters + 1):
        stage_results   = {}
        total_obj_value = 0
        start_time      = time.perf_counter()

        # FORWARD PASS
        for stage_idx in range(1, num_stages + 1):
            prev_B = initial_b if stage_idx == 1 else stage_results[stage_idx-1]["B_end"]
            Q, beta, B_end, stage_obj = _solve(stage_idx, prev_B, cuts.get(f'cuts_{stage_idx}', []))
            stage_results[stage_idx] = {"Q": Q, "beta": beta, "B_end": B_end, "stage_obj": stage_obj}
            total_obj_value += stage_obj

        # BACKWARD PASS
        for stage_idx in range(num_stages, 1, -1):
            prev_B = stage_results[stage_idx-1]["B_end"]
            Q_s, beta_s, _, _ = _solve(stage_idx, prev_B, cuts.get(f'cuts_{stage_idx}', []))
            alpha = Q_s - sum(beta_s[j] * prev_B[j] for j in Bset)
            cuts[f'cuts_{stage_idx-1}'].append((alpha, beta_s))

        LB_k = stage_results[1]['Q']
        UB_k = total_obj_value
        LB_container.append(LB_k)
        UB_container.append(UB_k)

        elapsed = time.perf_counter() - start_time
        print(f"Iter {k:02d} | LB = {LB_k:.6f} | UB = {UB_k:.6f} | "
              f"gap = {abs(UB_k-LB_k):.6f} | time = {elapsed:.2f}s")

        if abs(LB_k - prev_LB) < tol:
            print("SDDP converged.")
            break
        prev_LB = LB_k

    return LB_k, cuts, LB_container, UB_container
