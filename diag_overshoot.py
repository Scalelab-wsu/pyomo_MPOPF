"""Find which branch's cone gap EXPLODES after one full CCP step in window 10,
now that the head-switch gap is excluded. Prints the top branches by gap after
the step (both PVC diagonal and CMC cross-phase)."""
import os
_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca
os.environ.setdefault('SOC_INIT', 'max')

import numpy as np
import pandas as pd
from pyomo.environ import value

wd = os.path.dirname(os.path.abspath(__file__))
fp = os.path.join(wd, 'rawData', 'IEEE_9500', 'csvs')
dss_path = os.path.join(wd, 'rawData', 'IEEE_9500', 'dss_scripts', 'Master.dss')

from Parser.parse_phase_aware import parse_all_data_phase_aware
from OpenDss.OpenDssValidate import initialize_current_angles
from Build_Model.Constraints import get_or_build_model
import Build_Model.Constraints as _C
from Build_Model.Objective import cost_minimize_with_scd
from Build_Model.store import store_results
from Centralized.isocp import (_compute_gaps, initialize_model_variables,
                               _add_linear_directional_constraints_pvc,
                               _add_linear_directional_constraints_cmc, _safe_solve)

bus_data = pd.read_csv(os.path.join(fp, 'bus_data.csv'))
branch_data = pd.read_csv(os.path.join(fp, 'branch_data.csv'))
gen_data = pd.read_csv(os.path.join(fp, 'gen_data.csv'))
bat_data = pd.read_csv(os.path.join(fp, 'battery_data.csv'))
loadshape_data = pd.read_csv(os.path.join(fp, 'default_loadshape.csv'))
pvshape_data = pd.read_csv(os.path.join(fp, 'pv_loadshape.csv'))
price = 0.15 * loadshape_data['M'] + 0.15

ws = 10
d = parse_all_data_phase_aware(bus_data, branch_data, gen_data, bat_data,
                               loadshape=loadshape_data, pvshape=pvshape_data,
                               price=price, start_step=ws, n_steps=3)
d['v_min'] = {k: 0.9 for k in d['v_min']}
d['v_max'] = {k: 1.2 for k in d['v_max']}
d['I_ang'] = initialize_current_angles(d, dss_path, multi=True, start_step=ws)['I_ang']

_C.MODEL_CACHE.clear(); _C.SOLVER_CACHE.clear()
model, solver = get_or_build_model(d, cost_minimize_with_scd, solver='gurobi',
                                   alpha_scd=1e-3, stage_idx=None, isocp=True)
solver.solve(model)
prev = store_results(model)

e_pvc, e_cmc, lin_pvc, lin_cmc, max_gap = _compute_gaps(model)
print(f"init max_gap (switch excluded) = {max_gap:.3e}")

# one FULL CCP step
dir_pvc, dir_cmc = {}, {}
model, dir_pvc = _add_linear_directional_constraints_pvc(model, dir_pvc, e_pvc, lin_pvc, 0.5, 1e-4)
model, dir_cmc = _add_linear_directional_constraints_cmc(model, dir_cmc, e_cmc, lin_cmc, 0.5, 1e-4)
model = initialize_model_variables(model, prev)
tc, feas = _safe_solve(solver, model)
print(f"after full step: feasible={feas} ({tc})")

_zi = getattr(model, 'zero_impedance_diag', ())
# top PVC diagonal gaps after the step
rows = []
for t in model.Tset:
    for (i, j, ph) in model.branch_phase_set:
        if (i, j, ph) in _zi:
            continue
        P0 = value(model.P[t, i, j, ph]); Q0 = value(model.Q[t, i, j, ph])
        v0 = value(model.v[t, i, ph]); lpp0 = value(model.l[t, i, j, ph, ph])
        g = P0**2 + Q0**2 - v0*lpp0
        rows.append((abs(g), 'PVC', t, i, j, ph, P0, Q0, v0, lpp0,
                     d['r'][f'{ph}{ph}'][(i, j)], d['x'][f'{ph}{ph}'][(i, j)]))
rows.sort(reverse=True)
print("\nTOP PVC gaps after full step:")
for r in rows[:8]:
    g, _, t, i, j, ph, P0, Q0, v0, lpp0, rr, xx = r
    print(f"  gap={g:.3e}  t={t} {i}->{j} ph={ph}  P={P0:.3f} Q={Q0:.3f} v={v0:.4f} lpp={lpp0:.4f}  r={rr:.2e} x={xx:.2e}")
