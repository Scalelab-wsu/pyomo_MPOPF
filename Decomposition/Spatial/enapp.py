import os
import sys
import time
import pickle
import tempfile
import shutil
import multiprocessing as mp
import numpy as np
from collections import defaultdict, ChainMap

# Add project root so forkserver workers can import Build_Model etc.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca
_IDAES_BIN = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if _IDAES_BIN not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _IDAES_BIN + os.pathsep + os.environ.get('PATH', '')

# forkserver: one server forked from the clean parent; each worker is then forked
# from that server — safe for Gurobi and faster than spawn. Mirrors OTD_parallel.
# set_forkserver_preload causes the forkserver subprocess to receive sys.path from
# the parent, which lets it import Decomposition.Spatial.enapp to find the worker.
_MP_CTX = mp.get_context('forkserver')


from Build_Model.Constraints import build_pyomo_model, get_or_build_model
from Build_Model.Objective import pyomo_solve, cost_minimize_with_scd, loss_minimize_with_scd
from Build_Model.store import store_results
from Centralized.isocp import _solve_isocp, reset_isocp_cuts


def _area_worker_process(area_name, data_path, obj_fcn, solver, alpha_scd,
                         non_linear, isocp, p_control, integer,
                         single_battery_variable, recv_conn, send_conn):
    """One persistent process per area. Builds model ONCE then loops solve/send."""
    import traceback, sys
    try:
        if _IDAES_BIN not in os.environ.get('PATH', ''):
            os.environ['PATH'] = _IDAES_BIN + os.pathsep + os.environ.get('PATH', '')

        with open(data_path, 'rb') as f:
            data_area = pickle.load(f)
        data_area['v_max'] = {key: 1.2 for key in data_area['v_max'].keys()}
        data_area['v_min'] = {key: 0.9 for key in data_area['v_min'].keys()}

        model, s = get_or_build_model(
            data_area, obj_fcn, solver=solver, alpha_scd=alpha_scd,
            area_name=area_name, non_linear=non_linear, isocp=isocp,
            p_control=p_control, integer=integer,
            single_battery_variable=single_battery_variable,
        )
        send_conn.send(None)   # signal: model ready

        while True:
            msg = recv_conn.recv()
            if msg is None:    # shutdown
                break
            v_swing, p_L, q_L, run_isocp = msg
            for index in model.p_L:    model.p_L[index].value    = p_L[index]
            for index in model.q_L:    model.q_L[index].value    = q_L[index]
            for index in model.v_swing: model.v_swing[index].value = v_swing[index]
            # Always reset stale linearization cuts before the base LP solve.
            # Full ISOCP refinement only when boundaries have converged.
            if isocp:
                reset_isocp_cuts(model)
            s.solve(model)
            if isocp and run_isocp:
                socp_model, _ = _solve_isocp(prev_sol=store_results(model), model=model,
                                             model_solver=s,inner_tol=1e-3)
                send_conn.send(store_results(socp_model))
            else:
                send_conn.send(store_results(model))
    except Exception:
        tb = traceback.format_exc()
        with open(f'/tmp/enapp_worker_{area_name}.log', 'w') as f:
            f.write(tb)
        print(f'[EnAPP worker {area_name}] CRASHED:\n{tb}', file=sys.stderr, flush=True)
        raise

def process_area(data_areas, area_name, obj_fcn, solver,alpha_scd=1e-3,prev_solution=None, non_linear=False,isocp=False, p_control=False, integer=False,single_battery_variable=False):

    data_areas['v_max'] = {key:1.1 for key in data_areas['v_max'].keys()}
    model,model_solver = get_or_build_model(data_areas, obj_fcn, solver,alpha_scd=alpha_scd,stage_idx=None, area_name=area_name,non_linear=non_linear, isocp=isocp, p_control=p_control, integer=integer,single_battery_variable=single_battery_variable)

    # Parameter updates remain the same
    for index in model.p_L:
        model.p_L[index].value = data_areas['p_L'][index]
    for index in model.q_L:
        model.q_L[index].value = data_areas['q_L'][index]
    for index in model.v_swing:
        model.v_swing[index].value = data_areas['v_swing'][index]

    # # Warm-start from previous solution if available
    # if prev_solution is not None:
    #     for var_name, var_values in prev_solution.items():
    #         var = getattr(model, var_name)
    #         for index, value in var_values.items():
    #             var[index].value = value  # Set initial values
    if isocp:
        reset_isocp_cuts(model)
    model_solver.solve(model)
    solutions = store_results(model)
    if isocp:
        socp_model, _ = _solve_isocp(prev_sol=solutions, model=model,model_solver=model_solver,gamma=0.5,inner_tol=1e-3,gap_tol=1e-3)
        solutions = store_results(socp_model)
        return area_name,solutions
    return area_name, solutions


def initialize_shared(area_info, data):
    shared_vars = {}
    for area in area_info.keys():
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"] = [np.zeros((data['T'], 3))]
            shared_vars[f"{area}_{conn_area}_q"] = [np.zeros((data['T'], 3))]
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_v"] = [np.ones((data['T'], 3))]
    return shared_vars

## computing local by alpha sharing
def compute_locals(area_info, area_results,shared_vars,alpha):
    p_local, q_local, v_local = {}, {}, {}
    for area in area_info.keys():
        area_p = area_results[area]['P']
        area_q = area_results[area]['Q']
        area_v = area_results[area]['v']

        # Upstream connections
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            local_node = area_info[area]['up_local_node_id'][idx]
            p_key = f"{area}_{conn_area}_p"
            q_key = f"{area}_{conn_area}_q"
            p_local[p_key] = np.vstack([area_p[key] for key in area_p
                                        if key[1] == local_node]).reshape((-1, 3))
            q_local[q_key] = np.vstack([area_q[key] for key in area_q
                                        if key[1] == local_node]).reshape((-1, 3))
            ## alpha sharing
            p_local[p_key] = (1 - alpha)*p_local[p_key] + alpha * shared_vars[p_key][-1]
            q_local[q_key] = (1 - alpha) * q_local[q_key] + alpha * shared_vars[q_key][-1]
        # Downstream connections
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            v_key = f"{area}_{conn_area}_v"
            v_local[v_key] = np.vstack([np.sqrt(area_v[key]) for key in area_v
                                        if key[1] == local_node]).reshape((-1, 3))
            ## alpha sharing
            v_local[v_key] = (1 - alpha) * v_local[v_key] + alpha * shared_vars[v_key][-1]
    return p_local, q_local, v_local

def update_area_values(area_info, data_by_area, p_local, q_local, v_local):
    for area in area_info.keys():
        # Update downstream loads
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph_idx, ph in enumerate("abc"):
                    data_by_area[area]['p_L'][t, local_node, ph] = \
                        p_local[f"{conn_area}_{area}_p"][t - 1, ph_idx]
                    data_by_area[area]['q_L'][t, local_node, ph] = \
                        q_local[f"{conn_area}_{area}_q"][t - 1, ph_idx]

        # Update upstream voltages
        for idx, conn_area in enumerate(area_info[area]['up_area']):
            local_node = area_info[area]['up_local_node_id'][idx]
            for t in data_by_area[area]['Tset']:
                for ph_idx, ph in enumerate("abc"):
                    data_by_area[area]['v_swing'][t, local_node, ph] = \
                        v_local[f"{conn_area}_{area}_v"][t - 1, ph_idx]
    return data_by_area


def share_local(area_info, shared_vars, p_local, q_local, v_local):
    for area in area_info.keys():
        for conn_area in area_info[area]['down_areas']:
            shared_vars[f"{area}_{conn_area}_v"].append(v_local[f"{area}_{conn_area}_v"])
        for conn_area in area_info[area]['up_area']:
            shared_vars[f"{area}_{conn_area}_p"].append(p_local[f"{area}_{conn_area}_p"])
            shared_vars[f"{area}_{conn_area}_q"].append(q_local[f"{area}_{conn_area}_q"])
    return shared_vars


def arrange_solution_by_areas(area_info, area_results):
    # Remap local node IDs to global IDs
    for area in area_info.keys():
        for idx, conn_area in enumerate(area_info[area]['down_areas']):
            local_node = area_info[area]['down_local_node_id'][idx]
            global_node = area_info[conn_area]['up_global_node_id'][0]

            for var_type in ['P', 'Q']:
                updated = {}
                for (t, i, k, ph), val in area_results[area][var_type].items():
                    if k == local_node:
                        updated[(t, i, global_node, ph)] = val
                    else:
                        updated[(t, i, k, ph)] = val
                area_results[area][var_type] = updated

    # Collect all solutions
    dopf = defaultdict(dict)
    for area, results in area_results.items():
        for var_name, values in results.items():
            dopf[var_name][area] = values
    return dopf


def merge_solutions(dopf):
    merged = {
        'P_subs': dopf['P_subs']['area1'],
        'Q_subs': dopf['Q_subs']['area1'],
        'P': dict(ChainMap(*[dopf['P'][a] for a in dopf['P']])),
        'Q': dict(ChainMap(*[dopf['Q'][a] for a in dopf['Q']])),
        'v': dict(ChainMap(*[dopf['v'][a] for a in dopf['v']])),
        'p_D': dict(ChainMap(*[dopf['p_D'][a] for a in dopf['p_D']])),
        'q_D': dict(ChainMap(*[dopf['q_D'][a] for a in dopf['q_D']])),
        'P_c': dict(ChainMap(*[dopf['P_c'][a] for a in dopf['P_c']])),
        'P_d': dict(ChainMap(*[dopf['P_d'][a] for a in dopf['P_d']])),
        'B': dict(ChainMap(*[dopf['B'][a] for a in dopf['B']])),
    }
    return merged


def exclude_dummies(dopfVals):
    def _is_dummy_key(key):
        # For P/Q: keys are (t, from_bus, to_bus, ph)
        # For v: keys are (t, bus, ph)
        return isinstance(key, tuple) and any(isinstance(x, str) and x.startswith('D') for x in key)

    filtered = {}
    for var, dct in dopfVals.items():
        if var in ['P', 'Q', 'v']:
            filtered[var] = {k: v for k, v in dct.items() if not _is_dummy_key(k)}
        else:
            filtered[var] = dct
    return filtered

def solve_EnAPP(data, data_by_area, area_info, obj_fcn, *, solver, alpha_scd=1e-3,
                max_iterations=50, alpha=0, non_linear=False, isocp=False,
                p_control=False, integer=False, single_battery_variable=False):
    shared_vars = initialize_shared(area_info, data)
    convergence = {}
    objective = {}
    areas = list(area_info.keys())
    t0 = time.perf_counter()

    # Serialise each area's data to a temp file (done once in parent).
    # Workers receive a file path — avoids large IPC pickle on forkserver.
    _tmpdir = tempfile.mkdtemp(prefix='enapp_worker_')
    data_paths = {}
    for area in areas:
        path = os.path.join(_tmpdir, f'{area}.pkl')
        with open(path, 'wb') as f:
            pickle.dump(data_by_area[area], f, protocol=pickle.HIGHEST_PROTOCOL)
        data_paths[area] = path

    # Launch one persistent process per area — all build models in parallel
    send_conns, recv_conns = {}, {}
    procs = []
    t_launch_start = time.perf_counter()
    for area in areas:
        p_recv, c_send = _MP_CTX.Pipe(duplex=False)   # child → parent
        c_recv, p_send = _MP_CTX.Pipe(duplex=False)   # parent → child
        p = _MP_CTX.Process(
            target=_area_worker_process,
            args=(area, data_paths[area], obj_fcn, solver, alpha_scd,
                  non_linear, isocp, p_control, integer, single_battery_variable,
                  c_recv, c_send),
            daemon=True,
        )
        p.start()
        send_conns[area] = p_send
        recv_conns[area] = p_recv
        procs.append(p)

    print(f"  Launching {len(areas)} dedicated worker processes...", flush=True)
    for area in areas:
        recv_conns[area].recv()   # wait until model is built
    t_build = time.perf_counter() - t_launch_start
    print(f"  All models built in {t_build:.2f}s | starting iterations", flush=True)

    area_results = {}
    converged = False
    try:
        for iteration in range(1, max_iterations + 1):
            tk = time.perf_counter()

            # run_isocp=False during EnAPP iterations (use fast base SOCP)
            for area in areas:
                send_conns[area].send((
                    dict(data_by_area[area]['v_swing']),
                    dict(data_by_area[area]['p_L']),
                    dict(data_by_area[area]['q_L']),
                    False,
                ))
            area_results = {area: recv_conns[area].recv() for area in areas}

            p_local, q_local, v_local = compute_locals(area_info, area_results, shared_vars, alpha)
            data_by_area = update_area_values(area_info, data_by_area, p_local, q_local, v_local)
            shared_vars = share_local(area_info, shared_vars, p_local, q_local, v_local)

            max_diff = 0
            for var_list in shared_vars.values():
                if len(var_list) >= 2:
                    diff = np.max(np.abs(var_list[-1] - var_list[-2]))
                    max_diff = max(max_diff, diff)
            tol = max_diff
            convergence[iteration] = tol

            if obj_fcn == cost_minimize_with_scd:
                objective[iteration] = area_results['area1']['objective_value']
            else:
                objective[iteration] = sum(area_results[a]['objective_value'] for a in areas)

            iter_t = time.perf_counter() - tk
            print(f"  iter {iteration:02d} | ΔTol = {tol:.6f} | t = {iter_t:.2f}s")
            if tol < 1e-4:
                converged = True
                print(f"  Converged | total = {time.perf_counter() - t0:.2f}s")
                break
            alpha = alpha / 2

        # Final ISOCP refinement pass once EnAPP boundaries have converged.
        if isocp:
            print("  Running final ISOCP refinement...", flush=True)
            for area in areas:
                send_conns[area].send((
                    dict(data_by_area[area]['v_swing']),
                    dict(data_by_area[area]['p_L']),
                    dict(data_by_area[area]['q_L']),
                    True,
                ))
            area_results = {area: recv_conns[area].recv() for area in areas}
            print("  ISOCP refinement done.", flush=True)
    finally:
        for area in areas:
            try: send_conns[area].send(None)
            except Exception: pass
        for p in procs:
            p.join(timeout=5)
        shutil.rmtree(_tmpdir, ignore_errors=True)

    dopf = arrange_solution_by_areas(area_info, area_results)
    return exclude_dummies(merge_solutions(dopf)), objective, convergence

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import pandas as pd
    from Parser.parse_phase_aware import parse_all_data_phase_aware
    from Build_Model.Objective import cost_minimize_with_scd
    from OpenDss.OpenDssValidate import initialize_current_angles
    from Decomposition.Spatial.area_information import IEEE_123_area_info, IEEE_9500_area_info
    from Decomposition.Spatial.separate_areas import split_data_into_areas

    # system_name = 'IEEE_123'
    system_name = 'IEEE_9500'
    wd       = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
    filepath = os.path.join(wd, 'rawData', system_name, 'csvs')
    dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')

    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price          = 0.15 * loadshape_data['M'] + 0.15

    obj       = cost_minimize_with_scd
    solver    = 'gurobi'
    alpha_scd = 1e-2
    multi = True
    non_linear = False
    isocp     = True
    p_control = False
    integer   = False
    single_battery_variable = False

    area_info = eval(f'{system_name}_area_info')

    t_parse = time.perf_counter()
    print("Parsing data...")
    data = parse_all_data_phase_aware(bus_data, branch_data, gen_data, bat_data,
                                      loadshape=loadshape_data, pvshape=pvshape_data,
                                      price=price, n_steps=24)
    data['v_min'] = {k: 0.9 for k in data['v_min']}
    data['v_max'] = {k: 1.2 for k in data['v_max']}
    if non_linear or isocp:
        angles = initialize_current_angles(data, dss_path, multi=True)
        data['I_ang'] = angles['I_ang']
    data_by_area = split_data_into_areas(data, area_info)
    t_parse_done = time.perf_counter()
    print(f"  Parse done in {t_parse_done - t_parse:.2f}s")

    n_areas = len(area_info)
    print(f"\nEnAPP | system={system_name} | areas={n_areas} | solver={solver} | isocp={isocp}")

    t0 = time.perf_counter()
    vals, obj_hist, conv = solve_EnAPP(
        data, data_by_area, area_info, obj,
        solver=solver, alpha_scd=alpha_scd, max_iterations=50, alpha=0,
        non_linear=non_linear, isocp=isocp, p_control=p_control,
        integer=integer, single_battery_variable=single_battery_variable
    )
    t_total = time.perf_counter() - t0

    n_iters   = len(obj_hist)
    converged = (conv.get(n_iters, float('inf')) < 1e-4) if conv else False
    final_obj = obj_hist[n_iters] if obj_hist else float('nan')

    print(f"\n{'='*55}")
    print(f"  Solver       : {solver} | isocp={isocp} | areas={n_areas}")
    print(f"  Parse time   : {t_parse_done - t_parse:.2f}s")
    print(f"  EnAPP total  : {t_total:.2f}s  (parse NOT included)")
    print(f"  Converged    : {converged}")
    print(f"  Iterations   : {n_iters}")
    print(f"  Objective    : {final_obj:.6f}")
    print(f"  P_subs       : {sum(vals['P_subs'].values())*1e3:.2f} kW")
    print(f"  Q_subs       : {sum(vals['Q_subs'].values())*1e3:.2f} kVAr")
    print(f"{'='*55}")
