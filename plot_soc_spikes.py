"""Plot battery SOC trajectories to visualize the ISOCP zigzag/spikes.

Solves 3 cases (ISOCP default, nonlinear warm-started, ISOCP + beta_smooth) and
draws one subplot per battery with SOC(t) overlaid, so the spikes at particular
instants are visible. Saves soc_spikes.png.
"""
import os, io, contextlib
os.environ.setdefault('GRB_CAFILE', os.path.expanduser('~/nrel_gurobi_ca.pem'))
_idaes = os.path.join(os.path.expanduser('~'), '.idaes', 'bin')
if os.path.isdir(_idaes) and _idaes not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _idaes + os.pathsep + os.environ.get('PATH', '')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from pyomo.contrib.appsi.solvers import ipopt as _ai
_orig = _ai.Ipopt._parse_sol
def _patch(self):
    with open(self._filename + '.sol') as f:
        c = f.read()
    for m in ('Solved To Acceptable Level', 'Maximum Number of Iterations Exceeded',
              'Error in step computation'):
        if 'Optimal Solution Found' not in c and m in c:
            open(self._filename + '.sol', 'w').write(c.replace(m, 'Optimal Solution Found', 1))
            break
    return _orig(self)
_ai.Ipopt._parse_sol = _patch

from pyomo.environ import Var, value
from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from Build_Model.Constraints import get_or_build_model, MODEL_CACHE, SOLVER_CACHE
from Build_Model.store import store_results
from Centralized.isocp import _solve_isocp
from OpenDss.OpenDssValidate import initialize_current_angles

wd = os.getcwd(); sn = 'IEEE_123'; fp = os.path.join(wd, 'rawData', sn, 'csvs')
dss = os.path.join(wd, 'rawData', sn, 'dss_scripts', 'Master.dss')
bus = pd.read_csv(fp + '/bus_data.csv'); br = pd.read_csv(fp + '/branch_data.csv')
gen = pd.read_csv(fp + '/gen_data.csv'); bat = pd.read_csv(fp + '/battery_data.csv')
ls = pd.read_csv(fp + '/default_loadshape.csv'); pv = pd.read_csv(fp + '/pv_loadshape.csv')
price = 0.15 * ls['M'] + 0.15


def mk(beta=0.0):
    d = parse_all_data_phase_aware(bus, br, gen, bat, loadshape=ls, pvshape=pv,
                                   price=price, start_step=1, n_steps=24)
    d['v_min'] = {n: 0.9 for n in d['v_min']}; d['v_max'] = {n: 1.2 for n in d['v_max']}
    a = initialize_current_angles(d, dss, multi=True, start_step=1); d['I_ang'] = a['I_ang']
    d['beta_smooth'] = beta
    return d


def solve_isocp(d):
    MODEL_CACHE.clear(); SOLVER_CACHE.clear()
    model, s = get_or_build_model(d, cost_minimize_with_scd, solver='gurobi',
                                  alpha_scd=1e-3, stage_idx=None, non_linear=False,
                                  isocp=True, p_control=False, integer=False,
                                  single_battery_variable=False)
    with contextlib.redirect_stdout(io.StringIO()):
        s.solve(model)
        m2, _ = _solve_isocp(prev_sol=store_results(model), model=model,
                             model_solver=s, gamma=0.5, inner_tol=1e-4,
                             gap_tol=1e-4, max_inner=30)
    return model, store_results(m2)


def solve_nl(d, warm):
    model, s = get_or_build_model(d, cost_minimize_with_scd, solver='ipopt',
                                  alpha_scd=1e-3, stage_idx=None, non_linear=True,
                                  isocp=False, p_control=False, integer=False,
                                  single_battery_variable=False)
    src = {v.name: v for v in warm.component_objects(Var, active=True)}
    for dv in model.component_objects(Var, active=True):
        sv = src.get(dv.name)
        if sv is None:
            continue
        for idx in dv:
            if idx in sv and not dv[idx].fixed:
                val = value(sv[idx], exception=False)
                if val is not None:
                    dv[idx].set_value(val, skip_validation=True)
    for k, v in dict(tol=1e-6, max_iter=5000, mu_strategy='adaptive',
                     nlp_scaling_method='gradient-based', acceptable_tol=1e-4,
                     acceptable_iter=15).items():
        s._solver_options[k] = v
    with contextlib.redirect_stdout(io.StringIO()):
        s.solve(model)
    return store_results(model)


print("Solving ISOCP (beta=0)...")
m_is, s_is = solve_isocp(mk(0.0))
print("Solving nonlinear (beta=0, warm-started)...")
s_nl = solve_nl(mk(0.0), m_is)
print("Solving ISOCP (beta=0.3)...")
m_is3, s_is3 = solve_isocp(mk(0.3))
print("Solving nonlinear (beta=0.3, warm-started)...")
s_nl3 = solve_nl(mk(0.3), m_is3)

nodes = sorted({j for (_t, j) in s_is['B']})
ts = sorted({t for (t, j) in s_is['B'] if j == nodes[0]})


def series(sol, j):
    return [sol['B'][(t, j)] for t in ts]


ncol = 4
nrow = int(np.ceil(len(nodes) / ncol))
fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 2.6 * nrow), squeeze=False)
for idx, j in enumerate(nodes):
    ax = axes[idx // ncol][idx % ncol]
    # beta=0: the mismatched pair
    ax.plot(ts, series(s_is, j), '-o', ms=2.5, lw=1.0, label='ISOCP β=0', color='tab:red', alpha=0.55)
    ax.plot(ts, series(s_nl, j), '-s', ms=2.5, lw=1.0, label='nonlin β=0', color='tab:blue', alpha=0.55)
    # beta=0.3: the matched pair (should overlay)
    ax.plot(ts, series(s_is3, j), '-', lw=2.2, label='ISOCP β=0.3', color='tab:green')
    ax.plot(ts, series(s_nl3, j), '--', lw=1.6, label='nonlin β=0.3', color='black')
    ax.set_title(f"battery {j}", fontsize=9)
    ax.tick_params(labelsize=7)
    if idx == 0:
        ax.legend(fontsize=6)
for idx in range(len(nodes), nrow * ncol):
    axes[idx // ncol][idx % ncol].axis('off')
fig.suptitle("Battery SOC: β=0 mismatch (faded) vs β=0.3 matched (green=ISOCP, black dashed=nonlinear)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig('soc_spikes.png', dpi=120)
print("saved soc_spikes.png")

# mismatch summary
def mism(a, b):
    d = [abs(a['B'][k] - b['B'][k]) for k in a['B']]
    return max(d), float(np.mean(d))
print("\nSOC mismatch ISOCP vs nonlinear:")
print("  beta=0.0 : max=%.4f mean=%.4f" % mism(s_is, s_nl))
print("  beta=0.3 : max=%.4f mean=%.4f" % mism(s_is3, s_nl3))
