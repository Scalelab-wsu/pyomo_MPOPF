"""
Gamma sweep for DDDP-OTD on IEEE 123-bus, isocp=True.

Runs solve_DDDP_OTD for gamma in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9] and records:
  - total number of (outer) iterations
  - outer-loop gap per iteration  (|UB - LB| at each iter, in kW)
  - ISOCP inner gap per refinement iteration (max_gap from _solve_isocp)
  - total wall-clock computation time

Results are saved to gamma_sweep_results.json for later plotting.
"""
import os
import json
import time
import copy

# ── Gurobi / IDAES env fixes (mirror dddp_otd.py __main__) ──────────────────
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if os.path.isdir(_idaes_bin) and _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

import pandas as pd

from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from OpenDss.OpenDssValidate import initialize_current_angles
from Decomposition.Temporal.OTD_parallel import build_windows
from Decomposition.Temporal.dddp import solve_DDDP_OTD

# ── Configuration ─────────────────────────────────────────────────────────────
GAMMA_VALUES    = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
SYSTEM_NAME     = 'IEEE_123'
PARTITIONS      = 1       # single window: ISOCP is the primary convergence driver
OVERLAP         = 0
MAX_ITERS       = 25
TOL             = 1e-3
N_TOTAL         = 24
START_STEP      = 1
V_MIN, V_MAX    = 0.9, 1.2
SOLVER          = 'gurobi'
ALPHA_SCD       = 1e-3
NON_LINEAR      = False
ISOCP           = True
P_CONTROL       = False
INTEGER         = False
SINGLE_BAT_VAR  = False
OBJ             = cost_minimize_with_scd

RESULTS_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'gamma_sweep_results.json')

# ── Data paths ────────────────────────────────────────────────────────────────
wd          = os.path.dirname(os.path.abspath(__file__))
filepath    = os.path.join(wd, 'rawData', SYSTEM_NAME, 'csvs')
dss_path    = os.path.join(wd, 'rawData', SYSTEM_NAME, 'dss_scripts', 'Master.dss')

bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
price          = 0.15 * loadshape_data['M'] + 0.15


def _build_window_data(windows):
    """Parse and assemble window_data_map. Called once per sweep run."""
    window_data_map = {}
    for i in range(1, PARTITIONS + 1):
        w = windows[i]
        d = parse_all_data_phase_aware(
            bus_data, branch_data, gen_data, bat_data,
            loadshape=loadshape_data, pvshape=pvshape_data,
            price=price, start_step=w['ws'], n_steps=w['n'],
        )
        d['v_min']  = {k: V_MIN for k in d['v_min']}
        d['v_max']  = {k: V_MAX for k in d['v_max']}
        d['ws']     = w['ws']
        d['we']     = w['we']
        d['ce']     = w['ce']
        d['prev_B'] = dict(d['b0'])

        if NON_LINEAR or ISOCP:
            angles     = initialize_current_angles(d, dss_path, multi=True,
                                                    start_step=w['ws'])
            d['I_ang'] = angles['I_ang']
        window_data_map[i] = d
    return window_data_map


def _run_one_gamma(gamma, windows, window_data_map):
    """Run DDDP-OTD for a single gamma value and return collected metrics."""
    # Deep-copy so each gamma run gets a pristine data map
    wdm  = copy.deepcopy(window_data_map)
    b0   = dict(wdm[1]['b0'])

    print(f"\n{'='*60}")
    print(f"  gamma = {gamma}")
    print(f"{'='*60}")

    t_wall = time.perf_counter()
    vals, B_final, converged, timing = solve_DDDP_OTD(
        wdm, windows, b0,
        OBJ, SOLVER, ALPHA_SCD,
        NON_LINEAR, ISOCP, P_CONTROL, INTEGER, SINGLE_BAT_VAR,
        gamma=gamma,
        max_iters=MAX_ITERS,
        tol=TOL,
    )
    total_time = time.perf_counter() - t_wall

    lb_hist = timing['lb_history']
    ub_hist = timing['ub_history']
    # Per-outer-iteration absolute gap (kW)
    outer_gap_per_iter = [abs(ub - lb) for ub, lb in zip(ub_hist, lb_hist)]

    result = {
        'gamma':               gamma,
        'total_s':             total_time,
        'n_iters':             timing['n_iters'],
        'converged':           converged,
        'outer_gap_per_iter':  outer_gap_per_iter,
        'lb_history':          lb_hist,
        'ub_history':          ub_hist,
        'iter_times':          timing['iter_times'],
        # ISOCP inner-loop max_gap per inner iteration (from final refinement)
        'isocp_gap_history':   timing.get('isocp_gap_history', []),
    }

    print(f"\n  gamma={gamma} | iters={timing['n_iters']} | "
          f"converged={converged} | total_time={total_time:.1f}s")
    if outer_gap_per_iter:
        print(f"  max outer gap = {max(outer_gap_per_iter):.3e} kW  "
              f"| final outer gap = {outer_gap_per_iter[-1]:.3e} kW")
    if result['isocp_gap_history']:
        print(f"  ISOCP inner iters = {len(result['isocp_gap_history'])-1} "
              f"| init gap = {result['isocp_gap_history'][0]:.3e} "
              f"| final gap = {result['isocp_gap_history'][-1]:.3e}")
    return result


if __name__ == '__main__':
    windows = build_windows(N_TOTAL, PARTITIONS, OVERLAP)

    print(f"\nDDDP-OTD gamma sweep | {SYSTEM_NAME} | T={N_TOTAL}"
          f" | P={PARTITIONS} | isocp={ISOCP}")
    print(f"  gamma values: {GAMMA_VALUES}")

    print("\nParsing window data (once)...")
    t_parse = time.perf_counter()
    window_data_map = _build_window_data(windows)
    print(f"  Parse done in {time.perf_counter() - t_parse:.2f}s")

    all_results = {}
    for gamma in GAMMA_VALUES:
        res = _run_one_gamma(gamma, windows, window_data_map)
        all_results[str(gamma)] = res
        # Save incrementally after each gamma so partial results are preserved
        # if a later run crashes or hangs.
        with open(RESULTS_FILE, 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"  [saved {RESULTS_FILE} after gamma={gamma}]")

    print(f"\nAll results saved to {RESULTS_FILE}")

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'gamma':>6} | {'n_iters':>7} | {'total_s':>9} | "
          f"{'ISOCP_iters':>11} | {'final_ISOCP_gap':>15} | {'converged':>9}")
    print('-' * 75)
    for gamma in GAMMA_VALUES:
        r = all_results[str(gamma)]
        isocp_h  = r['isocp_gap_history']
        n_isocp  = len(isocp_h) - 1 if isocp_h else 0
        final_ig = isocp_h[-1] if isocp_h else float('nan')
        print(f"  {gamma:>4}  | {r['n_iters']:>7} | {r['total_s']:>9.1f} | "
              f"{n_isocp:>11} | {final_ig:>15.3e} | {str(r['converged']):>9}")
