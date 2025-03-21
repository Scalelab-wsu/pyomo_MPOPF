#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import multiprocessing as mp
from time import perf_counter

# === Import your existing modules/functions ===
from Build_Model.Constraints import build_pyomo_model
from Build_Model.Objective import pyomo_solve, cost_minimize, loss_minimize
from Parser.parse import parse_all_data
from separate_areas import split_data_into_areas
from Build_Model.store import store_results
from pyomo.environ import value, sqrt

# ----------------------------------------------------------------
# Example 'area_info' from your snippet.
# The key difference for ALGORITHM 2 is you also designate a
# "leading subsystem" for each link.  For instance:
#   (area1, area2) => area1 is the leader
#   (area1, area3) => area1 is the leader
#   (area2, area4) => area2 is the leader
# You can choose any scheme you like, as long as for each
# pair (n, m) exactly one is designated leader.
# ----------------------------------------------------------------
area_info = {
    'area1': {
        'up_area': [],
        'up_global_node_id': [1],
        'up_local_node_id': [1],
        'down_areas': ['area2', 'area3'],
        'down_local_node_id': ['D12', 'D13'],
        'down_global_node_id': [15, 20],
        'data_dir': 'area1',
        # For ALGO 2: specify who is "leader" for each link
        # If area1 is leader for area2 and area3, we do:
        'leaders': ['area1', 'area1']
    },
    'area2': {
        'up_area': ['area1'],
        'up_global_node_id': [117],
        'up_local_node_id': ['D21'],
        'down_areas': ['area4'],
        'down_local_node_id': ['D24'],
        'down_global_node_id': [62],
        'data_dir': 'area2',
        # If area1 was designated leader for (1-2), area2 is follower.
        # For link (area2 -> area4), let's assume area2 is the leader:
        'leaders': [None, 'area2']  # 'None' placeholder for up_area link
    },
    'area3': {
        'up_area': ['area1'],
        'up_global_node_id': [118],
        'up_local_node_id': ['D31'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir': 'area3',
        # area1 is the leader for (area1-area3), so area3 is follower
        'leaders': [None]
    },
    'area4': {
        'up_area': ['area2'],
        'up_global_node_id': [125],
        'up_local_node_id': ['D42'],
        'down_areas': [],
        'down_local_node_id': [],
        'down_global_node_id': [],
        'data_dir': 'area4',
        # area2 is the leader for (area2-area4), so area4 is follower
        'leaders': [None]
    }
}


def build_admm_objective(model, **kwargs):
    """
    This is your custom objective that adds the ADMM penalty terms
    for the local x minus the shared z, etc.
    """
    area_name = model.area_name
    area_info = model.area_info
    shared_vars = model.shared_vars
    dual_vars = model.dual_vars
    rho = model.rho

    # Start with normal OPF cost
    f = cost_minimize(model)

    # For each time step, add ADMM penalty and dual terms
    for tt in model.Tset:
        t = tt - 1
        # Upstream link
        for idx, up_area in enumerate(area_info[area_name]['up_area']):
            # retrieve last known consensus from shared_vars
            local_node_id = area_info[area_name]['up_local_node_id'][idx]
            # get references to shared/dual for that link
            shared_p = shared_vars[f"{area_name}_{up_area}_p"][-1]
            shared_q = shared_vars[f"{area_name}_{up_area}_q"][-1]
            shared_v = shared_vars[f"{area_name}_{up_area}_v"][-1]
            dual_p = dual_vars[f"lambda_{area_name}_{up_area}_p"][-1]
            dual_q = dual_vars[f"lambda_{area_name}_{up_area}_q"][-1]
            dual_v = dual_vars[f"lambda_{area_name}_{up_area}_v"][-1]

            # local x
            x_p = sum(model.P[tt, i, k, ph]
                      for (i, k) in model.Lset if i == local_node_id
                      for ph in "abc")
            x_q = sum(model.Q[tt, i, k, ph]
                      for (i, k) in model.Lset if i == local_node_id
                      for ph in "abc")
            x_v = sum(model.v[tt, i, ph]
                      for i in model.Nset if i == local_node_id
                      for ph in "abc")

            # Add the ADMM terms
            f += (
                    dual_p[t][0] * (x_p - shared_p[t][0]) +
                    dual_q[t][0] * (x_q - shared_q[t][0]) +
                    dual_v[t][0] * (x_v - shared_v[t][0] ** 2) +
                    (rho / 2) * (
                            (x_p - shared_p[t][0]) ** 2 +
                            (x_q - shared_q[t][0]) ** 2 +
                            (x_v - shared_v[t][0] ** 2) ** 2
                    )
            )
        # Downstream link
        for idx, down_area in enumerate(area_info[area_name]['down_areas']):
            shared_p = shared_vars[f"{area_name}_{down_area}_p"][-1]
            shared_q = shared_vars[f"{area_name}_{down_area}_q"][-1]
            shared_v = shared_vars[f"{area_name}_{down_area}_v"][-1]
            dual_p = dual_vars[f"lambda_{area_name}_{down_area}_p"][-1]
            dual_q = dual_vars[f"lambda_{area_name}_{down_area}_q"][-1]
            dual_v = dual_vars[f"lambda_{area_name}_{down_area}_v"][-1]

            local_node_id = area_info[area_name]['down_local_node_id'][idx]
            x_p = sum(model.P[tt, (i, k), ph]
                      for (i, k) in model.Lset if k == local_node_id
                      for ph in "abc")
            x_q = sum(model.Q[tt, (i, k), ph]
                      for (i, k) in model.Lset if k == local_node_id
                      for ph in "abc")
            x_v = sum(model.v[tt, i, ph]
                      for i in model.Nset if i == local_node_id
                      for ph in "abc")

            f += (
                    dual_p[t][0] * (x_p - shared_p[t][0]) +
                    dual_q[t][0] * (x_q - shared_q[t][0]) +
                    dual_v[t][0] * (x_v - shared_v[t][0] ** 2) +
                    (rho / 2) * (
                            (x_p - shared_p[t][0]) ** 2 +
                            (x_q - shared_q[t][0]) ** 2 +
                            (x_v - shared_v[t][0] ** 2) ** 2
                    )
            )
    return f


def process_area(data_for_area,
                 area_name,
                 area_info,
                 shared_vars,
                 dual_vars,
                 rho):
    """
    Solve the local subproblem for a single area,
    using the current shared_vars and dual_vars (from the last iteration).
    """
    # For safety, set v_max etc. if needed
    data_for_area['v_max'] = {
        key: 1.1 for key in data_for_area['v_max'].keys()
    }
    model = build_pyomo_model(data_for_area)
    # attach references
    model.area_name = area_name
    model.area_info = area_info
    model.shared_vars = shared_vars
    model.dual_vars = dual_vars
    model.rho = rho

    # Solve
    model = pyomo_solve(model, build_admm_objective)
    solutions = store_results(model)
    return area_name, solutions


def leading_subsystem_update(leader_area,
                             follower_area,
                             area_results,
                             shared_vars,
                             dual_vars,
                             rho):
    """
    Implements the "leading subsystem" step for the link between
    leader_area and follower_area.

    1. Gather x_local from both
    2. Leader updates z_{lf} = average of ( x_leader, x_follower )
    3. Leader sends updated z_{lf} to follower
    4. Both update dual variables accordingly
    """

    # Extract local solutions from area_results
    P_lead = area_results[leader_area]['P']
    Q_lead = area_results[leader_area]['Q']
    v_lead = area_results[leader_area]['v']

    P_foll = area_results[follower_area]['P']
    Q_foll = area_results[follower_area]['Q']
    v_foll = area_results[follower_area]['v']

    # Identify the local node IDs from area_info
    # Because we do up_area vs down_area, we must figure out
    # which direction the link is. For example, if 'follower_area'
    # is in 'down_areas' of 'leader_area', we do k == local_node_id, etc.
    # For simplicity, assume the same logic as your code:
    #   areaX_areaY_p means the flow from X to Y
    #   so we do a quick search in leader_area's area_info:
    leader_down = area_info[leader_area]['down_areas']
    leader_down_ids = area_info[leader_area]['down_local_node_id']

    leader_up = area_info[leader_area]['up_area']
    leader_up_ids = area_info[leader_area]['up_local_node_id']

    # We'll define a helper to find the correct local node ID
    # in the leader area that corresponds to the link to the follower:
    def find_local_node_id_for_link(leader, follower):
        if follower in area_info[leader]['down_areas']:
            idx = area_info[leader]['down_areas'].index(follower)
            return area_info[leader]['down_local_node_id'][idx], 'down'
        elif follower in area_info[leader]['up_area']:
            idx = area_info[leader]['up_area'].index(follower)
            return area_info[leader]['up_local_node_id'][idx], 'up'
        else:
            return None, None

    leader_node, direction = find_local_node_id_for_link(leader_area, follower_area)

    # Similarly for follower_area
    def find_local_node_id_for_link_follower(follower, leader):
        if leader in area_info[follower]['down_areas']:
            idx = area_info[follower]['down_areas'].index(leader)
            return area_info[follower]['down_local_node_id'][idx], 'down'
        elif leader in area_info[follower]['up_area']:
            idx = area_info[follower]['up_area'].index(leader)
            return area_info[follower]['up_local_node_id'][idx], 'up'
        else:
            return None, None

    follower_node, direction_f = find_local_node_id_for_link_follower(follower_area, leader_area)

    # Now gather the actual local flows (for each T, for each phase).
    # For simplicity, here we’ll do single-phase or 3-phase in a compressed form.
    # We'll create arrays of shape (T, 3).  We'll replicate your code logic:
    Tset = sorted(list(set(k[0] for k in P_lead.keys())))
    T = len(Tset)

    p_lead_arr = np.zeros((T, 3))
    p_foll_arr = np.zeros((T, 3))
    q_lead_arr = np.zeros((T, 3))
    q_foll_arr = np.zeros((T, 3))
    v_lead_arr = np.zeros((T, 3))
    v_foll_arr = np.zeros((T, 3))

    # Extract from leader
    # If direction == 'down', that means the local node ID is the "to" node for the lines in the sets.
    # This is the same logic from your code, but abbreviated.
    # You may need to adapt for your actual indexing.
    for t_idx, t in enumerate(Tset):
        for ph_idx, ph in enumerate("abc"):
            # leader side
            if direction == 'down':
                # that means on leader's side we do
                # x_p = sum( P[t,(i,k),ph] for (i,k) if k==leader_node )
                # etc.
                p_lead_arr[t_idx, ph_idx] = sum(P_lead[key]
                                                for key in P_lead.keys()
                                                if key[0] == t and key[1][1] == leader_node and key[2] == ph)
                q_lead_arr[t_idx, ph_idx] = sum(Q_lead[key]
                                                for key in Q_lead.keys()
                                                if key[0] == t and key[1][1] == leader_node and key[2] == ph)
                v_lead_arr[t_idx, ph_idx] = sum(v_lead[key]
                                                for key in v_lead.keys()
                                                if key[0] == t and key[1] == leader_node and key[2] == ph)
            else:
                # direction == 'up'
                p_lead_arr[t_idx, ph_idx] = sum(P_lead[key]
                                                for key in P_lead.keys()
                                                if key[0] == t and key[1][0] == leader_node and key[2] == ph)
                q_lead_arr[t_idx, ph_idx] = sum(Q_lead[key]
                                                for key in Q_lead.keys()
                                                if key[0] == t and key[1][0] == leader_node and key[2] == ph)
                v_lead_arr[t_idx, ph_idx] = sum(v_lead[key]
                                                for key in v_lead.keys()
                                                if key[0] == t and key[1] == leader_node and key[2] == ph)

            # follower side
            if direction_f == 'down':
                p_foll_arr[t_idx, ph_idx] = sum(P_foll[key]
                                                for key in P_foll.keys()
                                                if key[0] == t and key[1][1] == follower_node and key[2] == ph)
                q_foll_arr[t_idx, ph_idx] = sum(Q_foll[key]
                                                for key in Q_foll.keys()
                                                if key[0] == t and key[1][1] == follower_node and key[2] == ph)
                v_foll_arr[t_idx, ph_idx] = sum(v_foll[key]
                                                for key in v_foll.keys()
                                                if key[0] == t and key[1] == follower_node and key[2] == ph)
            else:
                p_foll_arr[t_idx, ph_idx] = sum(P_foll[key]
                                                for key in P_foll.keys()
                                                if key[0] == t and key[1][0] == follower_node and key[2] == ph)
                q_foll_arr[t_idx, ph_idx] = sum(Q_foll[key]
                                                for key in Q_foll.keys()
                                                if key[0] == t and key[1][0] == follower_node and key[2] == ph)
                v_foll_arr[t_idx, ph_idx] = sum(v_foll[key]
                                                for key in v_foll.keys()
                                                if key[0] == t and key[1] == follower_node and key[2] == ph)

    # Leader computes the consensus
    p_z = 0.5 * (p_lead_arr + p_foll_arr)
    q_z = 0.5 * (q_lead_arr + q_foll_arr)
    v_z = 0.5 * (v_lead_arr + v_foll_arr)  # or decide if you want sqrt averaging, etc.

    # Now store in shared_vars, e.g. "leader_follower_p"
    link_name = f"{leader_area}_{follower_area}"
    shared_vars[f"{link_name}_p"].append(p_z)
    shared_vars[f"{link_name}_q"].append(q_z)
    shared_vars[f"{link_name}_v"].append(v_z)

    # The follower also should store the same consensus under “follower_leader”
    # so that both use the same z.
    # (Because your code references areaX_areaY_p or areaY_areaX_p in local solves.)
    reverse_link = f"{follower_area}_{leader_area}"
    shared_vars[f"{reverse_link}_p"].append(p_z)
    shared_vars[f"{reverse_link}_q"].append(q_z)
    shared_vars[f"{reverse_link}_v"].append(v_z)

    # Next, the dual update.  Each area does its own
    # \lambda_n^{k+1} = \lambda_n^k + rho ( x_n^{k+1} - z_{nm}^{k+1} ).
    # So we compute the difference for each side and update.
    lam_p_lead = dual_vars[f"lambda_{leader_area}_{follower_area}_p"][-1] \
                 + rho * (p_lead_arr - p_z)
    lam_q_lead = dual_vars[f"lambda_{leader_area}_{follower_area}_q"][-1] \
                 + rho * (q_lead_arr - q_z)
    lam_v_lead = dual_vars[f"lambda_{leader_area}_{follower_area}_v"][-1] \
                 + rho * (v_lead_arr - v_z)

    lam_p_foll = dual_vars[f"lambda_{follower_area}_{leader_area}_p"][-1] \
                 + rho * (p_foll_arr - p_z)
    lam_q_foll = dual_vars[f"lambda_{follower_area}_{leader_area}_q"][-1] \
                 + rho * (q_foll_arr - q_z)
    lam_v_foll = dual_vars[f"lambda_{follower_area}_{leader_area}_v"][-1] \
                 + rho * (v_foll_arr - v_z)

    # Append them
    dual_vars[f"lambda_{leader_area}_{follower_area}_p"].append(lam_p_lead)
    dual_vars[f"lambda_{leader_area}_{follower_area}_q"].append(lam_q_lead)
    dual_vars[f"lambda_{leader_area}_{follower_area}_v"].append(lam_v_lead)

    dual_vars[f"lambda_{follower_area}_{leader_area}_p"].append(lam_p_foll)
    dual_vars[f"lambda_{follower_area}_{leader_area}_q"].append(lam_q_foll)
    dual_vars[f"lambda_{follower_area}_{leader_area}_v"].append(lam_v_foll)

    # That's it. The leader has updated z, and both leader/follower have updated duals.


if __name__ == "__main__":
    tic = perf_counter()
    wd = os.getcwd()
    # Adjust your own file paths:
    filepath = os.path.join(wd, "..", "rawData", "IEEE_123_other")

    # 1) Import CSV files (same as before)
    bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
    branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
    gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
    bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
    loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
    pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))

    price = [
        0.026, 0.025, 0.022, 0.02, 0.022, 0.024, 0.025, 0.026,
        0.028, 0.034, 0.038, 0.035, 0.036, 0.037, 0.038, 0.04,
        0.04, 0.03, 0.031, 0.029, 0.027, 0.025, 0.023, 0.026
    ]

    data = parse_all_data(bus_data, branch_data, gen_data, bat_data,
                          loadshape_data, pvshape_data, price)

    # 2) Split into sub-areas (same as before)
    data_by_area = split_data_into_areas(data)
    area_folders = ['area1', 'area2', 'area3', 'area4']

    # 3) Initialize shared (consensus) and dual variables
    #    *for each link*, as we did before
    shared_vars = {}
    dual_vars = {}
    rho = 0.5

    # For each area, for each neighbor link, we define arrays
    for area in area_folders:
        for down_area in area_info[area]['down_areas']:
            link = f"{area}_{down_area}"
            revlink = f"{down_area}_{area}"
            # Initialize with zeros (p,q) or ones (v):
            shared_vars[f"{link}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{link}_q"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{link}_v"] = [np.ones((data['T'], 3))]
            # Also reverse:
            shared_vars[f"{revlink}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{revlink}_q"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{revlink}_v"] = [np.ones((data['T'], 3))]

            dual_vars[f"lambda_{link}_p"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{link}_q"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{link}_v"] = [np.zeros((data['T'], 3))]
            # Reverse
            dual_vars[f"lambda_{revlink}_p"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{revlink}_q"] = [np.zeros((data['T'], 3))]
            dual_vars[f"lambda_{revlink}_v"] = [np.zeros((data['T'], 3))]

        # For up_areas similarly
        for up_area in area_info[area]['up_area']:
            link = f"{area}_{up_area}"
            revlink = f"{up_area}_{area}"
            if link not in shared_vars:  # avoid double creation
                shared_vars[f"{link}_p"] = [np.zeros((data['T'], 3))]
                shared_vars[f"{link}_q"] = [np.zeros((data['T'], 3))]
                shared_vars[f"{link}_v"] = [np.ones((data['T'], 3))]
                dual_vars[f"lambda_{link}_p"] = [np.zeros((data['T'], 3))]
                dual_vars[f"lambda_{link}_q"] = [np.zeros((data['T'], 3))]
                dual_vars[f"lambda_{link}_v"] = [np.zeros((data['T'], 3))]

            if revlink not in shared_vars:
                shared_vars[f"{revlink}_p"] = [np.zeros((data['T'], 3))]
                shared_vars[f"{revlink}_q"] = [np.zeros((data['T'], 3))]
                shared_vars[f"{revlink}_v"] = [np.ones((data['T'], 3))]
                dual_vars[f"lambda_{revlink}_p"] = [np.zeros((data['T'], 3))]
                dual_vars[f"lambda_{revlink}_q"] = [np.zeros((data['T'], 3))]
                dual_vars[f"lambda_{revlink}_v"] = [np.zeros((data['T'], 3))]

    # Create a multiprocessing Pool
    pool = mp.Pool(processes=len(area_folders))

    max_iterations = 50
    convergence = {}
    objective = {}

    for k_iter in range(max_iterations):
        # Step 2 (Algorithm 2): Each subsystem solves local DC-OPF in parallel
        results = pool.starmap(
            process_area,
            [(data_by_area[area], area, area_info, shared_vars, dual_vars, rho)
             for area in area_folders]
        )
        area_results = dict(results)

        #
        # Step 3,4,5 (Algorithm 2):
        # "Duplicated variables corresponding to z_g are sent to leading subsystem,
        #  leading subsystem updates z_g, then leading subsystem sends updated z_g
        #  to corresponding adjacent subsystem."
        #
        # In practice, we now identify each link (n <-> m).  Whichever area is the
        # designated "leader" for that link does the consensus update.
        #
        # We'll just systematically check "down_areas" of each area. If area is
        # the leader for that link, call leading_subsystem_update(...).
        #
        for area in area_folders:
            # For each downstream neighbor
            for idx, down_area in enumerate(area_info[area]['down_areas']):
                # Check if area_info[area]['leaders'][idx] == area => means area is leader
                if area_info[area]['leaders'][idx] == area:
                    # Then do leading update with "follower_area=down_area"
                    leading_subsystem_update(
                        leader_area=area,
                        follower_area=down_area,
                        area_results=area_results,
                        shared_vars=shared_vars,
                        dual_vars=dual_vars,
                        rho=rho
                    )
                # Otherwise, do nothing here: the leading side
                # will handle the update from the other direction.

        # Similarly, for up_areas. Possibly you also define
        #  area_info[area]['leaders_up'] or reuse the same list.
        #  In your snippet, you only defined 'leaders' for down_areas,
        #  but you can do something symmetrical if needed.

        #
        # Step 6 (Algorithm 2): Check stopping criteria
        #
        # We'll do a quick check similar to your "max_diff" approach:
        max_diff_area = []
        for link_name in shared_vars:
            arrs = shared_vars[link_name]
            if len(arrs) > 1:
                diff = np.linalg.norm(arrs[-1] - arrs[-2])
                max_diff_area.append(diff)
        # also check duals
        for lam_name in dual_vars:
            arrs = dual_vars[lam_name]
            if len(arrs) > 1:
                diff = np.linalg.norm(arrs[-1] - arrs[-2])
                max_diff_area.append(diff)

        tol = max(max_diff_area) if max_diff_area else 999.0
        convergence[k_iter] = tol
        # objective: just read from one area or sum if you want total cost
        objective_val = area_results['area1']['objective_value']  # or sum them
        objective[k_iter] = objective_val

        print(f"Iteration {k_iter}, tolerance={tol}, objective={objective_val}")

        if tol < 1e-6:
            print(f"Converged after {k_iter} iterations")
            print(f"Total objective value: {objective_val}")
            break

    pool.close()
    pool.join()
    print(f"Time for DOPF: {perf_counter() - tic} seconds")
