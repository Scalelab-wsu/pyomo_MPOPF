################################################################################
# A Minimal, Correct Example of ADMM for a 2-Area OPF-Like Problem in Pyomo
################################################################################
import pyomo.environ as pyo
import numpy as np

###############################################################################
# 1) Sample Data for Two Areas
###############################################################################
# Suppose each area has:
#   - one real bus (besides the boundary dummy),
#   - a local load,
#   - a local generator,
#   - half of the line connecting them.

# We store data in dictionaries. In a more elaborate code, you would parse CSVs.
area_data = {
    'area1': {
        'bus': 1,
        'load_p': 0.5,    # MW
        'gen_cost': 1.0,  # $/MW
        'line_r': 0.01,   # ohms or pu
        'line_x': 0.05,
        # We treat dummy bus as 'd1'
    },
    'area2': {
        'bus': 2,
        'load_p': 0.8,
        'gen_cost': 1.0,
        'line_r': 0.01,
        'line_x': 0.05,
        # We treat dummy bus as 'd2'
    }
}

# ADMM parameters
rho = 10.0
max_iter = 50
tolerance = 1e-6

###############################################################################
# 2) Define a function that builds a local Pyomo model for a given area
###############################################################################
def build_local_model(area_name, data):
    """
    Build a local Pyomo model with:
      - Bus voltage magnitude squared v_bus
      - Dummy bus voltage magnitude squared v_dummy
      - Real power generation p_gen
      - Real power flow p_flow from local bus->dummy
      - Slack or references for a substation if needed. (Here, we keep it simple.)
    """
    m = pyo.ConcreteModel()
    m.area_name = area_name

    # Parameters
    load_p = data['load_p']
    gen_cost = data['gen_cost']

    # Variables
    # For simplicity, define them all as nonnegative except flows can be negative in general
    m.v_bus   = pyo.Var(bounds=(0.9**2, 1.1**2), initialize=1.0)  # squared voltage at local bus
    m.v_dummy = pyo.Var(bounds=(0.9**2, 1.1**2), initialize=1.0)  # squared voltage at boundary dummy bus

    m.p_gen   = pyo.Var(bounds=(0.0, 10.0), initialize=1.0)
    m.q_gen   = pyo.Var(bounds=(-5, 5), initialize=0.0) # optional reactive

    # Real flow from local bus to dummy bus
    # Let it be any real number
    m.p_flow  = pyo.Var(bounds=(-10,10), initialize=0.0)
    m.q_flow  = pyo.Var(bounds=(-10,10), initialize=0.0)

    # We define an "objective" that is only the local cost. The ADMM penalty
    # will be added in the augmented_obj_function.
    def local_obj_expr(m):
        return gen_cost * m.p_gen   # linear cost
    m.local_obj = pyo.Objective(rule=local_obj_expr, sense=pyo.minimize)

    # Power balance at the local bus:
    #   p_gen - load_p - p_flow = 0
    def bus_balance_rule(m):
        return m.p_gen - load_p - m.p_flow == 0
    m.bus_balance = pyo.Constraint(rule=bus_balance_rule)

    # (Optional) simple Q-balance: q_gen - q_flow = 0 if there's no load Q
    def bus_q_balance_rule(m):
        return m.q_gen - m.q_flow == 0
    m.bus_q_balance = pyo.Constraint(rule=bus_q_balance_rule)

    # Very simple approximate "voltage drop" constraint
    # v_dummy - v_bus + 2*r*p_flow + 2*x*q_flow = 0, ignoring couplings
    # for a single-phase or single-wire approach
    r, x = data['line_r'], data['line_x']
    def kvl_rule(m):
        return (m.v_dummy - m.v_bus
                + 2*r*m.p_flow + 2*x*m.q_flow) == 0
    m.kvl = pyo.Constraint(rule=kvl_rule)

    # We'll store space for ADMM penalty in an external function,
    # so we won't finalize the objective here.  We'll "monkey-patch"
    # an attribute for the final objective.

    return m


###############################################################################
# 3) The "augmented_obj_function": adds ADMM penalty terms
###############################################################################
def augmented_obj_function(m, **kwargs):
    """
    This function is called after building the local model. We add
    dual/pentalty terms for:
      - real flow P_flow boundary
      - reactive flow Q_flow boundary
      - dummy node voltage v_dummy
    so they match the "shared variables" in ADMM.

    We'll do a simple approach:
      ADMM constraint for real flow: p_flow(area) + p_flow(other_area) = 0
      We'll store p_global as negative of area2's flow in shared_vars, etc.
    """

    # We retrieve parameters from the model's attributes, which were set by pyomo_solve()
    area_name   = m.area_name
    shared_vars = m.shared_vars
    dual_vars   = m.dual_vars
    rho         = m.rho

    # The local objective is the sum of:
    #   - the original local_obj
    #   - ADMM penalties
    local_obj = m.local_obj

    # We'll define shorter notation
    # Suppose we stored the relevant index for THIS area in e.g. shared_vars[area_name]['p_flow']
    # We'll do that in the main code below. Let's define:
    p_bar = shared_vars[area_name]['p_flow']   # float or array
    q_bar = shared_vars[area_name]['q_flow']
    v_bar = shared_vars[area_name]['v_dummy']

    # The dual variables:
    lam_p = dual_vars[area_name]['p_flow']
    lam_q = dual_vars[area_name]['q_flow']
    lam_v = dual_vars[area_name]['v_dummy']

    # Now build penalty terms. Here, each is a scalar.
    # p_flow, q_flow, v_dummy are each single Pyomo Var in this example.
    #
    # ADMM:   Lagrangian = lam_p * (p_flow - p_bar) + rho/2*(p_flow - p_bar)^2
    # We do the same for q_flow, v_dummy, etc.

    # Some prefer to do: lam_p * (m.p_flow - p_bar) + 0.5*rho*(m.p_flow - p_bar)^2
    # We'll do them each:
    penalty = ( lam_p*(m.p_flow - p_bar)
                + 0.5*rho*(m.p_flow - p_bar)**2
                + lam_q*(m.q_flow - q_bar)
                + 0.5*rho*(m.q_flow - q_bar)**2
                + lam_v*(m.v_dummy - v_bar)
                + 0.5*rho*(m.v_dummy - v_bar)**2 )

    return local_obj + penalty


###############################################################################
# 4) A helper to solve local model with the augmented objective
###############################################################################
def solve_local_model(m, shared_vars, dual_vars, rho):
    # Attach shared and dual variables, and penalty factor
    m.shared_vars = shared_vars
    m.dual_vars = dual_vars
    m.rho = rho

    # Deactivate the original objective to avoid conflicts
    m.local_obj.deactivate()

    # Replace the objective with the augmented Lagrangian
    m.obj = pyo.Objective(rule=augmented_obj_function, sense=pyo.minimize)

    # Solve the model
    solver = pyo.SolverFactory('gurobi')
    result = solver.solve(m, tee=False)

    return m



###############################################################################
# 5) Main ADMM loop
###############################################################################
def run_admm_2area(area_data, rho, max_iter, tol):
    """
    Build two local models, do ADMM iteration.
    We'll store for each area a dictionary of shared/dual variables:
       shared_vars['area1']['p_flow'] = a float
       ...
       dual_vars['area1']['p_flow']   = a float
    Then do the usual ADMM steps:
       1) Solve local subproblem
       2) Update global = average
       3) Update dual
    """
    # Build each local model
    m1 = build_local_model('area1', area_data['area1'])
    m2 = build_local_model('area2', area_data['area2'])

    # Initialize shared and dual variables.
    # We'll have 3 boundary variables: p_flow, q_flow, v_dummy
    # For clarity, we define that the "consensus" is that
    #   p_flow(area1) + p_flow(area2) = 0
    # so we'll store a single "p_bar1" for area1, and the "p_bar2" for area2
    # might be = - p_bar1 if we prefer.
    # But let's keep it simple: each area has its own "p_flow_bar" etc.
    # We'll enforce the average step as p_bar1 = (p_flow1 - p_flow2)/2, etc.
    shared_vars = {
       'area1': {
          'p_flow': 0.0,
          'q_flow': 0.0,
          'v_dummy': 1.0
       },
       'area2': {
          'p_flow': 0.0,
          'q_flow': 0.0,
          'v_dummy': 1.0
       }
    }
    dual_vars = {
       'area1': {
          'p_flow': 0.0,
          'q_flow': 0.0,
          'v_dummy': 0.0
       },
       'area2': {
          'p_flow': 0.0,
          'q_flow': 0.0,
          'v_dummy': 0.0
       }
    }

    # We'll do a simple iteration
    for it in range(max_iter):
        # 1) Solve each local model with the current shared/dual
        solve_local_model(m1, shared_vars, dual_vars, rho)
        solve_local_model(m2, shared_vars, dual_vars, rho)

        # Extract local solutions
        p_flow1 = pyo.value(m1.p_flow)
        q_flow1 = pyo.value(m1.q_flow)
        v_d1    = pyo.value(m1.v_dummy)

        p_flow2 = pyo.value(m2.p_flow)
        q_flow2 = pyo.value(m2.q_flow)
        v_d2    = pyo.value(m2.v_dummy)

        # 2) Compute new "global" or "consensus"
        #    We'll do the standard approach for a 2-area boundary:
        #      p_bar1 =  0.5*(p_flow1 - p_flow2)
        #      p_bar2 = -0.5*(p_flow1 - p_flow2)
        #    so that forcing p_flow1 -> p_bar1 and p_flow2 -> p_bar2 means
        #    p_flow1 + p_flow2 -> 0.
        #    Alternatively, we can do: p_bar1 = (p_flow1 + p_flow2)/2 if we
        #    want them equal in sign.  Just be consistent with bus-balance
        #    constraints.
        #
        #    Let's do a "they must sum to 0" approach:
        p_bar1 = 0.5*(p_flow1 - p_flow2)
        q_bar1 = 0.5*(q_flow1 - q_flow2)
        v_bar1 = 0.5*(v_d1 + v_d2)  # we want v_d1 = v_d2

        # For area2, we do the matching step:
        p_bar2 = -p_bar1   # so that p_flow1 + p_flow2 = 0 if each area tries p_flow - p_bar
        q_bar2 = -q_bar1
        v_bar2 = v_bar1    # because we want v_d2 = v_d1

        # 3) Update Lagrange multipliers
        #    lam1_{p} = lam1_{p} + rho*(p_flow1 - p_bar1)
        #    lam2_{p} = lam2_{p} + rho*(p_flow2 - p_bar2)
        old_lam1_p = dual_vars['area1']['p_flow']
        old_lam1_q = dual_vars['area1']['q_flow']
        old_lam1_v = dual_vars['area1']['v_dummy']

        old_lam2_p = dual_vars['area2']['p_flow']
        old_lam2_q = dual_vars['area2']['q_flow']
        old_lam2_v = dual_vars['area2']['v_dummy']

        new_lam1_p = old_lam1_p + rho*(p_flow1 - p_bar1)
        new_lam1_q = old_lam1_q + rho*(q_flow1 - q_bar1)
        new_lam1_v = old_lam1_v + rho*(v_d1 - v_bar1)

        new_lam2_p = old_lam2_p + rho*(p_flow2 - p_bar2)
        new_lam2_q = old_lam2_q + rho*(q_flow2 - q_bar2)
        new_lam2_v = old_lam2_v + rho*(v_d2 - v_bar2)

        dual_vars['area1']['p_flow'] = new_lam1_p
        dual_vars['area1']['q_flow'] = new_lam1_q
        dual_vars['area1']['v_dummy'] = new_lam1_v

        dual_vars['area2']['p_flow'] = new_lam2_p
        dual_vars['area2']['q_flow'] = new_lam2_q
        dual_vars['area2']['v_dummy'] = new_lam2_v

        # 4) Share global / consensus updates
        #    area1 sees p_bar1, etc. area2 sees p_bar2, ...
        shared_vars['area1']['p_flow']  = p_bar1
        shared_vars['area1']['q_flow']  = q_bar1
        shared_vars['area1']['v_dummy'] = v_bar1

        shared_vars['area2']['p_flow']  = p_bar2
        shared_vars['area2']['q_flow']  = q_bar2
        shared_vars['area2']['v_dummy'] = v_bar2

        # 5) Check convergence
        #    A typical primal residual:
        #       r_p1 = p_flow1 - p_bar1
        #       r_p2 = p_flow2 - p_bar2
        r_p1 = p_flow1 - p_bar1
        r_p2 = p_flow2 - p_bar2
        r_q1 = q_flow1 - q_bar1
        r_q2 = q_flow2 - q_bar2
        r_v1 = v_d1    - v_bar1
        r_v2 = v_d2    - v_bar2

        primal_resid = np.sqrt( r_p1**2 + r_p2**2 + r_q1**2 + r_q2**2 + r_v1**2 + r_v2**2 )

        if primal_resid < tol:
            print(f"[ADMM] Converged in {it} iterations.")
            break

        # Optionally print iteration info
        local_obj1 = pyo.value(m1.local_obj)
        local_obj2 = pyo.value(m2.local_obj)
        aug_obj1   = pyo.value(m1.obj)
        aug_obj2   = pyo.value(m2.obj)
        print(f"Iter={it}, Resid={primal_resid:.4g}, "
              f"Area1 LocalObj={local_obj1:.4g}, AugObj={aug_obj1:.4g}, "
              f"p_flow1={p_flow1:.4g}, v_dummy1={v_d1:.4g}  ||  "
              f"Area2 LocalObj={local_obj2:.4g}, AugObj={aug_obj2:.4g}, "
              f"p_flow2={p_flow2:.4g}, v_dummy2={v_d2:.4g}"
              )

    # After done, gather final solutions
    # e.g. final bus voltages, flows, etc.
    solution = {
       'area1': {
           'p_flow': pyo.value(m1.p_flow),
           'q_flow': pyo.value(m1.q_flow),
           'v_bus':  pyo.value(m1.v_bus),
           'v_dummy':pyo.value(m1.v_dummy),
           'p_gen':  pyo.value(m1.p_gen),
           'q_gen':  pyo.value(m1.q_gen),
       },
       'area2': {
           'p_flow': pyo.value(m2.p_flow),
           'q_flow': pyo.value(m2.q_flow),
           'v_bus':  pyo.value(m2.v_bus),
           'v_dummy':pyo.value(m2.v_dummy),
           'p_gen':  pyo.value(m2.p_gen),
           'q_gen':  pyo.value(m2.q_gen),
       }
    }
    return solution

###############################################################################
# 6) Finally, run the code as a "main"
###############################################################################
if __name__ == "__main__":
    sol = run_admm_2area(area_data, rho=rho, max_iter=max_iter, tol=tolerance)
    print("Final ADMM solution:\n", sol)
