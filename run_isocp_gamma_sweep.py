"""
ISOCP gamma sweep — centralized on IEEE 123-bus.

Uses solve_copf directly (no DDDP worker overhead) for each gamma value.

Recorded per gamma:
  - isocp_gap_history : max cone-violation per ISOCP inner iteration
  - total_s           : total wall-clock time

Saved to:
  run_logs/isocp_{system_name}_gamma_{val}.pkl
"""

import os
import sys
import time
import pickle

# ── env fixes ─────────────────────────────────────────────────────────────────
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

_idaes_bin = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if _idaes_bin not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes_bin + os.pathsep + os.environ.get('PATH', '')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from OpenDss.OpenDssValidate import initialize_current_angles
from Centralized.copf import solve_copf
from Build_Model.Constraints import MODEL_CACHE

# ── Configuration ─────────────────────────────────────────────────────────────
SYSTEM_NAME  = 'IEEE_123'
GAMMA_VALUES = [0.7]  # ← change sweep range here
N_TOTAL      = 24
V_MIN        = 0.9
V_MAX        = 1.2
SOLVER       = 'gurobi'
ALPHA_SCD    = 1e-3
NON_LINEAR   = False
ISOCP        = True
MAX_INNER    = 50
INNER_TOL    = 1e-4
GAP_TOL      = 1e-4

wd = os.path.dirname(os.path.abspath(__file__))

if __name__ == '__main__':
    filepath = os.path.join(wd, 'rawData', SYSTEM_NAME, 'csvs')
    dss_path = os.path.join(wd, 'rawData', SYSTEM_NAME, 'dss_scripts', 'Master.dss')
    save_dir = os.path.join(wd, 'run_logs')
    os.makedirs(save_dir, exist_ok=True)

    # ── Load CSV data ──────────────────────────────────────────────────────────
    bus_data       = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
    branch_data    = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
    gen_data       = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
    bat_data       = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
    loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
    pvshape_data   = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
    price          = 0.15 * loadshape_data['M'] + 0.15

    # ── Parse full-horizon data once ──────────────────────────────────────────
    t_parse = time.perf_counter()
    print(f"\nParsing full-horizon data for {SYSTEM_NAME}...")
    data = parse_all_data_phase_aware(
        bus_data, branch_data, gen_data, bat_data,
        loadshape=loadshape_data, pvshape=pvshape_data,
        price=price, start_step=1, n_steps=N_TOTAL)
    data['v_min'] = {k: V_MIN for k in data['v_min']}
    data['v_max'] = {k: V_MAX for k in data['v_max']}
    if NON_LINEAR or ISOCP:
        angles        = initialize_current_angles(data, dss_path, multi=True,
                                                  start_step=1)
        data['I_ang'] = angles['I_ang']
    print(f"  Parse done in {time.perf_counter() - t_parse:.2f}s")

    # ── Gamma sweep — use solve_copf directly (no DDDP worker overhead) ───────
    print(f"\nStarting ISOCP gamma sweep | gamma values: {GAMMA_VALUES}")

    for gamma in GAMMA_VALUES:
        print(f"\n{'='*60}")
        print(f"  gamma = {gamma}", flush=True)
        print(f"{'='*60}")

        # Clear model cache so each gamma gets a fresh model
        MODEL_CACHE.clear()

        t0  = time.perf_counter()
        sol = solve_copf(
            data,
            obj=cost_minimize_with_scd,
            solver=SOLVER,
            alpha_scd=ALPHA_SCD,
            non_linear=NON_LINEAR,
            isocp=ISOCP,
            gamma=gamma,
            inner_tol=INNER_TOL,
            gap_tol=GAP_TOL,
            max_inner=MAX_INNER,
        )
        total_s = time.perf_counter() - t0

        isocp_gaps = sol.get('isocp_gap_history', [])

        if isocp_gaps:
            print(f"  total={total_s:.2f}s | ISOCP iters={len(isocp_gaps)}"
                  f" | init max_gap={isocp_gaps[0]:.3e}"
                  f" | final max_gap={isocp_gaps[-1]:.3e}")
        else:
            print(f"  total={total_s:.2f}s | no ISOCP gap history")

        save_data = {
            'system_name':       SYSTEM_NAME,
            'n_total':           N_TOTAL,
            'isocp':             ISOCP,
            'gamma':             gamma,
            'isocp_gap_history': isocp_gaps,
            'total_s':           total_s,
        }
        gamma_tag = f"{gamma:.2f}".replace('.', 'p')
        save_path = os.path.join(save_dir,
                                 f'isocp_{SYSTEM_NAME}_gamma_{gamma_tag}.pkl')
        with open(save_path, 'wb') as f:
            pickle.dump(save_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"  Saved → {save_path}")

    print(f"\n{'='*60}")
    print(f"Gamma sweep complete. Files in {save_dir}/")
