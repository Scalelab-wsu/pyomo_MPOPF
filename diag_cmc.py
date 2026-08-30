"""Diagnostic: separate PVC (diagonal) vs CMC (cross-phase) cone gaps at the
INITIAL relaxed SOCP for an easy morning window vs a hard midday window, and
inspect the ISOCP cut-coefficient magnitudes (to explain the Gurobi
'zero or small (<1e-13) coefficients, ignored' warning and the CMC infeasibility).

Prints, per window:
  - PVC max/mean |gap|, CMC max/mean |gap|
  - # active CMC pairs (pass the 0.5*sqrt(lpp*lqq) safety filter)
  - # CMC pairs whose leading cut coeff 2*lpq0 < 1e-12 (would be dropped)
  - cross-phase loss-coefficient sign census: how many (r_pq cosΔδ + x_pq sinΔδ)
    are POSITIVE (objective drives l_pq -> 0, conflicting with the CMC cone)
"""
import os

# Gurobi WLS license via NREL proxy needs the CA cert (as main.py sets at import)
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

import numpy as np
import pandas as pd
from pyomo.environ import value

os.environ.setdefault('SOC_INIT', 'max')

wd = os.path.dirname(os.path.abspath(__file__))
system_name = 'IEEE_9500'
filepath = os.path.join(wd, 'rawData', system_name, 'csvs')
dss_path = os.path.join(wd, 'rawData', system_name, 'dss_scripts', 'Master.dss')

from Parser.parse_phase_aware import parse_all_data_phase_aware
from OpenDss.OpenDssValidate import initialize_current_angles
from Build_Model.Constraints import get_or_build_model
import Build_Model.Constraints as _C
from Build_Model.Objective import cost_minimize_with_scd

bus_data = pd.read_csv(os.path.join(filepath, 'bus_data.csv'))
branch_data = pd.read_csv(os.path.join(filepath, 'branch_data.csv'))
gen_data = pd.read_csv(os.path.join(filepath, 'gen_data.csv'))
bat_data = pd.read_csv(os.path.join(filepath, 'battery_data.csv'))
loadshape_data = pd.read_csv(os.path.join(filepath, 'default_loadshape.csv'))
pvshape_data = pd.read_csv(os.path.join(filepath, 'pv_loadshape.csv'))
price = 0.15 * loadshape_data['M'] + 0.15


def analyze(ws, n=3):
    d = parse_all_data_phase_aware(bus_data, branch_data, gen_data, bat_data,
                                   loadshape=loadshape_data, pvshape=pvshape_data,
                                   price=price, start_step=ws, n_steps=n)
    d['v_min'] = {k: 0.9 for k in d['v_min']}
    d['v_max'] = {k: 1.2 for k in d['v_max']}
    ang = initialize_current_angles(d, dss_path, multi=True, start_step=ws)
    d['I_ang'] = ang['I_ang']

    _C.MODEL_CACHE.clear(); _C.SOLVER_CACHE.clear()   # avoid stage_idx=None cache collision
    model, solver = get_or_build_model(d, cost_minimize_with_scd, solver='gurobi',
                                       alpha_scd=1e-3, stage_idx=None, isocp=True)
    solver.solve(model)

    pvc, cmc = [], []
    n_active_cmc = 0
    n_tiny_coeff = 0
    n_pos_losscoef = 0
    n_cross = 0
    r, x = d['r'], d['x']
    worst_pvc = (0.0, None)
    for t in model.Tset:
        for (i, j, ph) in model.branch_phase_set:
            P0 = value(model.P[t, i, j, ph]); Q0 = value(model.Q[t, i, j, ph])
            v0 = value(model.v[t, i, ph]); lpp0 = value(model.l[t, i, j, ph, ph])
            g = abs(P0**2 + Q0**2 - v0*lpp0)
            pvc.append(g)
            if g > worst_pvc[0]:
                rr = r[f'{ph}{ph}'][(i, j)]; xx = x[f'{ph}{ph}'][(i, j)]
                worst_pvc = (g, (t, i, j, ph, P0, Q0, v0, lpp0, rr, xx))
        for (i, j, p, q) in model.branch_phase_pair_set:
            if p == q:
                continue
            if model.l[t, i, j, p, q].is_fixed():
                continue
            lpq0 = value(model.l[t, i, j, p, q])
            lpp0 = value(model.l[t, i, j, p, p]); lqq0 = value(model.l[t, i, j, q, q])
            safe = lpq0 >= 0.5*np.sqrt(max(lpp0*lqq0, 0.0))
            if safe:
                n_active_cmc += 1
                cmc.append(abs(lpq0**2 - lpp0*lqq0))
            if 2*lpq0 < 1e-12:
                n_tiny_coeff += 1
            # cross-phase loss coefficient sign (real power)
            n_cross += 1
            dd = value(model.delta[t, i, j, p]) - value(model.delta[t, i, j, q])
            coef = r[f'{p}{q}'][(i, j)]*np.cos(dd) + x[f'{p}{q}'][(i, j)]*np.sin(dd)
            if coef > 0:
                n_pos_losscoef += 1

    pvc = np.array(pvc); cmc = np.array(cmc) if cmc else np.array([0.0])
    print(f"\n===== window {ws}-{ws+n-1} (pvM peaks midday) =====")
    print(f"  PVC |gap|: max={pvc.max():.3e}  mean={pvc.mean():.3e}")
    print(f"  CMC |gap|: max={cmc.max():.3e}  mean={cmc.mean():.3e}  (active pairs={n_active_cmc})")
    print(f"  CMC pairs with 2*lpq0 < 1e-12 (coeff dropped by Gurobi): {n_tiny_coeff}")
    print(f"  cross-phase pairs with POSITIVE loss coeff (obj drives l_pq->0): "
          f"{n_pos_losscoef}/{n_cross} ({100*n_pos_losscoef/max(n_cross,1):.1f}%)")
    g, info = worst_pvc
    if info:
        t, i, j, ph, P0, Q0, v0, lpp0, rr, xx = info
        floor = (P0**2 + Q0**2) / v0 if v0 else float('nan')
        print(f"  WORST PVC branch: t={t} {i}->{j} ph={ph}  gap={g:.3e}")
        print(f"    P0={P0:.4f} Q0={Q0:.4f} v0={v0:.4f}  lpp0={lpp0:.4f} "
              f"cone_floor=(P^2+Q^2)/v={floor:.4f}  lpp0/floor={lpp0/max(floor,1e-12):.2f}x")
        print(f"    branch r_pp={rr:.3e}  x_pp={xx:.3e}  (r/x={rr/xx if xx else float('nan'):.3f})")


if __name__ == '__main__':
    analyze(7)    # easy morning window
    analyze(16)   # hard midday window
