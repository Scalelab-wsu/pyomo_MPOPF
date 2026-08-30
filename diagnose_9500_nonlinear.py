"""
Diagnostic script for IEEE-9500 nonlinear OPF infeasibility.
Checks:
1. Branch orientation: does DFS flip any branches? Do branch_phases keys match?
2. Angle coverage: does initialize_current_angles populate ALL (t,fb,tb,ph) that the model needs?
3. Zero/NaN angles: are any angles missing, zero (placeholder), or NaN?
4. Load/substation voltage consistency between model data and OpenDSS
5. Flipped angles: when OpenDSS branch direction differs from model, is I_ang flipped correctly?
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import networkx as nx

wd = os.path.dirname(os.path.abspath(__file__))
system_name = 'IEEE_9500'
filepath     = os.path.join(wd, "rawData", system_name, "csvs")
dss_path     = os.path.join(wd, "rawData", system_name, "dss_scripts", "Master.dss")

bus_data       = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data    = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
gen_data       = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data       = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data   = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
price          = 0.15 * loadshape_data['M'] + 0.15

from Parser.parse_phase_aware import parse_all_data_phase_aware
start_step = 1
n_steps    = 1
data = parse_all_data_phase_aware(
    bus_data, branch_data, gen_data, bat_data,
    loadshape=loadshape_data, pvshape=pvshape_data, price=price,
    start_step=start_step, n_steps=n_steps
)
data['v_min'] = {node: 0.9 for node in data['v_min'].keys()}
data['v_max'] = {node: 1.2 for node in data['v_max'].keys()}

print("=" * 70)
print("SECTION 1 – Branch/bus set sizes")
print("=" * 70)
print(f"  Nset (buses):    {len(data['Nset'])}")
print(f"  Lset (branches): {len(data['Lset'])}")
print(f"  Dset (PV units): {len(data['Dset'])}")
print(f"  Bset (batteries):{len(data['Bset'])}")
print(f"  Tset:            {data['Tset']}")
print(f"  Substation bus:  {data['substationBus']}")

# ── branch_phase_set entries ──────────────────────────────────────────────────
bp_set = [(fb, tb, ph)
          for (fb, tb) in data['Lset']
          for ph in data['branch_phases'][(fb, tb)]]
print(f"  branch_phase entries (model expects): {len(bp_set)}")

# ── check if branch_phases has entries for every Lset member ─────────────────
missing_bp = [(fb, tb) for (fb, tb) in data['Lset']
              if (fb, tb) not in data['branch_phases']]
print(f"  Branches in Lset missing from branch_phases: {len(missing_bp)}")
if missing_bp:
    print("  First 5:", missing_bp[:5])

# ── DFS vs CSV orientation ────────────────────────────────────────────────────
print()
print("=" * 70)
print("SECTION 2 – DFS orientation check")
print("=" * 70)
branch_filtered = branch_data.loc[branch_data.status != 'OPEN'].copy()
branch_filtered['from_name'] = branch_filtered['from_name'].astype(str)
branch_filtered['to_name']   = branch_filtered['to_name'].astype(str)
csv_branch_set = set(zip(branch_filtered['from_name'], branch_filtered['to_name']))
flipped_dfs = [(fb,tb) for (fb,tb) in data['Lset'] if (fb,tb) not in csv_branch_set]
print(f"  Branches where DFS direction != CSV direction: {len(flipped_dfs)}")
if flipped_dfs:
    for fb, tb in flipped_dfs[:5]:
        print(f"    DFS: ({fb},{tb})  CSV had: ({tb},{fb})")

# ── OpenDSS angle initialisation ─────────────────────────────────────────────
print()
print("=" * 70)
print("SECTION 3 – OpenDSS angle initialisation")
print("=" * 70)

from OpenDss.OpenDssValidate import initialize_current_angles
angles = initialize_current_angles(data, dss_path, multi=True, start_step=start_step)
I_ang = angles['I_ang']
I_mag = angles['I_mag']

print(f"  I_ang entries populated by OpenDSS: {len(I_ang)}")
print(f"  I_mag entries populated by OpenDSS: {len(I_mag)}")
print(f"  Model needs (T x branch_phase_set): {len(data['Tset']) * len(bp_set)}")

# ── Coverage: which (t,fb,tb,ph) are MISSING from I_ang ──────────────────────
missing_ang = []
for t in data['Tset']:
    for (fb, tb, ph) in bp_set:
        if (t, fb, tb, ph) not in I_ang:
            missing_ang.append((t, fb, tb, ph))

print(f"\n  Missing I_ang entries (model branches not in OpenDSS output): {len(missing_ang)}")
if missing_ang:
    print("  First 10:")
    for entry in missing_ang[:10]:
        t, fb, tb, ph = entry
        print(f"    t={t}  ({fb},{tb})  ph={ph}  [branch_phases={data['branch_phases'].get((fb,tb),'???')}]")

    # Which OpenDSS element types did those missing branches come from?
    missing_pairs = set((fb, tb) for _, fb, tb, _ in missing_ang)
    print(f"\n  Unique missing (fb,tb) pairs: {len(missing_pairs)}")
    # look up in branch_data
    for fb, tb in list(missing_pairs)[:5]:
        row = branch_filtered[(branch_filtered.from_name == fb) & (branch_filtered.to_name == tb)]
        if row.empty:
            row = branch_filtered[(branch_filtered.from_name == tb) & (branch_filtered.to_name == fb)]
        if not row.empty:
            print(f"    ({fb},{tb}): type={row.iloc[0]['type']}, name={row.iloc[0]['name']}, phases={row.iloc[0]['phases']}")

# ── Zero / NaN angles ─────────────────────────────────────────────────────────
zero_ang  = [(k, v) for k, v in I_ang.items() if abs(v) < 1e-10]
nan_ang   = [(k, v) for k, v in I_ang.items() if math.isnan(v)]
print(f"\n  Angles == 0 (possible placeholder): {len(zero_ang)}")
print(f"  Angles NaN:                          {len(nan_ang)}")
if zero_ang:
    print("  First 5 zero-angle branches:")
    for k, v in zero_ang[:5]:
        t, fb, tb, ph = k
        print(f"    t={t} ({fb},{tb}) ph={ph}  I_mag={I_mag.get(k,'?'):.4f}")

# ── Angle distribution summary ───────────────────────────────────────────────
ang_vals = list(I_ang.values())
print(f"\n  Angle stats (deg): min={min(np.degrees(v) for v in ang_vals):.1f}  "
      f"max={max(np.degrees(v) for v in ang_vals):.1f}  "
      f"mean={np.mean([np.degrees(v) for v in ang_vals]):.1f}")

# ── Check per-phase angle range for 3-phase branches ─────────────────────────
print()
print("=" * 70)
print("SECTION 4 – Phase angle consistency (3-phase branches)")
print("=" * 70)
abc_branches = [(fb,tb) for (fb,tb) in data['Lset'] if data['branch_phases'][(fb,tb)] == ['a','b','c']]
print(f"  3-phase branches (abc): {len(abc_branches)}")

# Sample 5 three-phase branches and print angles
import random
random.seed(42)
sample = random.sample(abc_branches, min(5, len(abc_branches)))
for fb, tb in sample:
    t = data['Tset'][0]
    ang_a = np.degrees(I_ang.get((t,fb,tb,'a'), float('nan')))
    ang_b = np.degrees(I_ang.get((t,fb,tb,'b'), float('nan')))
    ang_c = np.degrees(I_ang.get((t,fb,tb,'c'), float('nan')))
    mag_a = I_mag.get((t,fb,tb,'a'), float('nan'))
    mag_b = I_mag.get((t,fb,tb,'b'), float('nan'))
    mag_c = I_mag.get((t,fb,tb,'c'), float('nan'))
    print(f"  ({fb[:20]},{tb[:20]}):")
    print(f"    a: {ang_a:7.2f}° mag={mag_a:.4f}")
    print(f"    b: {ang_b:7.2f}° mag={mag_b:.4f}")
    print(f"    c: {ang_c:7.2f}° mag={mag_c:.4f}")
    if not any(math.isnan(x) for x in [ang_a, ang_b, ang_c]):
        ab = ang_a - ang_b
        bc = ang_b - ang_c
        print(f"    a-b diff: {ab:.1f}°  b-c diff: {bc:.1f}° (expected ~120)")

# ── SECTION 5: OpenDSS vs model loads ────────────────────────────────────────
print()
print("=" * 70)
print("SECTION 5 – Load magnitude check: model vs OpenDSS nameplate")
print("=" * 70)
import opendssdirect as dss

dss.Text.Command("clear")
script_dir = os.path.dirname(os.path.abspath(
    os.path.join(wd, "OpenDss", "OpenDssValidate.py")))
script_path = os.path.join(script_dir, dss_path)
dss.Text.Command(f'Redirect "{script_path}"')

load_profile = [
    0.677, 0.6256, 0.6087, 0.5833, 0.58028, 0.6025, 0.657, 0.7477,
    0.832, 0.88, 0.94, 0.989, 0.985, 0.98, 0.9898, 0.999,
    1, 0.958, 0.936, 0.913, 0.876, 0.876, 0.828, 0.756
]
load_mult = ' '.join(map(str, load_profile))
dss.Text.Command(f'New Loadshape.loadshape npts=24 interval=1 mult=({load_mult})')
dss.Text.Command(f"BatchEdit Load..* Daily=loadshape")
dss.Text.Command("Set mode = Daily")
dss.Text.Command("Set stepsize = 1h")
dss.Text.Command("Set number = 1")
dss.Text.Command(f"Set hour = 0")
dss.Text.Command("solve")
print(f"  OpenDSS converged: {dss.Solution.Converged()}")

P_base = 1e6
t = 1

# model total load
p_load_model = sum(data['p_L'][t, i, ph] for t_, i, ph in data['p_L'] if t_ == t) * 1e3
q_load_model = sum(data['q_L'][t, i, ph] for t_, i, ph in data['q_L'] if t_ == t) * 1e3

# OpenDSS total load (actual at this hour)
p_dss_total = 0; q_dss_total = 0
load_id = dss.Loads.First()
while load_id > 0:
    lname = dss.Loads.Name()
    dss.Circuit.SetActiveElement(f"Load.{lname}")
    powers = dss.CktElement.Powers()
    nph = dss.CktElement.NumPhases()
    p_dss_total += sum(powers[2*i] for i in range(nph))
    q_dss_total += sum(powers[2*i+1] for i in range(nph))
    load_id = dss.Loads.Next()

print(f"  Model p_L total (t=1): {p_load_model:.2f} kW")
print(f"  OpenDSS load total  :  {p_dss_total:.2f} kW  (q={q_dss_total:.2f} kVAr)")
print(f"  Model q_L total (t=1): {q_load_model:.2f} kVAr")

# OpenDSS nameplate (rated kW)
p_rated = sum(dss.Loads.kW() * 0 + dss.Loads.kW() for _ in [None]
              if dss.Loads.First()) # trick
p_rated = 0
load_id = dss.Loads.First()
while load_id > 0:
    p_rated += dss.Loads.kW()
    load_id = dss.Loads.Next()
print(f"  OpenDSS rated (nameplate) load: {p_rated:.2f} kW")
print(f"  Model load at t=1 / OpenDSS actual: {p_load_model/p_dss_total:.4f} (expect ~1.0)")

# ── SECTION 6: substation voltage ─────────────────────────────────────────────
print()
print("=" * 70)
print("SECTION 6 – Substation voltage (v_swing)")
print("=" * 70)
sub_bus = data['substationBus'][0]
print(f"  Substation bus: {sub_bus}")
for ph in data['bus_phases'][sub_bus]:
    vsw = data['v_swing'].get((1, sub_bus, ph), 'MISSING')
    print(f"  v_swing[t=1, {sub_bus}, {ph}] = {vsw}  (squared in model: {vsw**2 if vsw != 'MISSING' else '?'})")

# Actual OpenDSS substation voltage
dss.Circuit.SetActiveBus(sub_bus)
vmag_pu = dss.Bus.puVmagAngle()
print(f"  OpenDSS substation voltages (pu, angle): {vmag_pu[:6]}")

# ── SECTION 7: check I_ang for the first branch ──────────────────────────────
print()
print("=" * 70)
print("SECTION 7 – Angle sign convention check (first few branches from substation)")
print("=" * 70)
bfs_edges = data['bfs_edges']
print(f"  BFS edges from substation (first 5): {bfs_edges[:5]}")
for (fb, tb) in bfs_edges[:3]:
    if (fb, tb) in data['Lset']:
        for ph in data['branch_phases'][(fb, tb)]:
            t = 1
            ang = I_ang.get((t, fb, tb, ph), None)
            mag = I_mag.get((t, fb, tb, ph), None)
            if ang is not None:
                print(f"  ({fb[:25]},{tb[:25]}) ph={ph}  ang={np.degrees(ang):.2f}°  mag={mag:.4f} A(pu)")

# ── SECTION 8: check that p_D matches OpenDSS PV at t=1 ──────────────────────
print()
print("=" * 70)
print("SECTION 8 – PV generation check")
print("=" * 70)
p_pv_model = sum(data['p_D'][t, i, ph] for t_, i, ph in data['p_D'] if t_ == t) * 1e3
print(f"  Model p_D total (t=1): {p_pv_model:.2f} kW")
pv_p_dss = 0
pv_id = dss.PVsystems.First()
while pv_id > 0:
    dss.Circuit.SetActiveElement(f"PVSystem.{dss.PVsystems.Name()}")
    powers = dss.CktElement.Powers()
    nph = dss.CktElement.NumPhases()
    pv_p_dss -= sum(powers[2*i] for i in range(nph))
    pv_id = dss.PVsystems.Next()
print(f"  OpenDSS PV total (t=1): {pv_p_dss:.2f} kW")

# ── SECTION 9: check for any impossible angle difference > 180° ────────────────
print()
print("=" * 70)
print("SECTION 9 – Angle differences > 180° between phases (model uses cos/sin)")
print("=" * 70)
bad_diffs = []
for (fb, tb) in data['Lset']:
    phases = data['branch_phases'][(fb, tb)]
    if len(phases) < 2:
        continue
    t = 1
    for i, ph1 in enumerate(phases):
        for ph2 in phases[i+1:]:
            a1 = I_ang.get((t, fb, tb, ph1), None)
            a2 = I_ang.get((t, fb, tb, ph2), None)
            if a1 is None or a2 is None:
                continue
            diff_deg = abs(np.degrees(a1 - a2))
            if diff_deg > 180:
                diff_deg = 360 - diff_deg
            # Flag if diff is NOT close to 120 (expected for balanced 3-phase)
            if len(phases) == 3 and abs(diff_deg - 120) > 30:
                bad_diffs.append((fb, tb, ph1, ph2, np.degrees(a1), np.degrees(a2), np.degrees(a1-a2)))

print(f"  3-phase branches with phase angle diff NOT ~120°: {len(bad_diffs)}")
if bad_diffs:
    print("  First 5 problematic:")
    for fb, tb, p1, p2, a1, a2, diff in bad_diffs[:5]:
        print(f"    ({fb[:20]},{tb[:20]}) {p1}-{p2}: ang={a1:.1f}°,{a2:.1f}°  diff={diff:.1f}°")

# ── SECTION 10: check cos/sin loss term magnitude for first branch ─────────────
print()
print("=" * 70)
print("SECTION 10 – Sample loss-term magnitude (r*cos + x*sin) for a few branches")
print("=" * 70)
r = data['r']
x = data['x']
t = 1
for (fb, tb) in bfs_edges[:5]:
    if (fb, tb) not in data['Lset']:
        continue
    phases = data['branch_phases'][(fb, tb)]
    if len(phases) < 2:
        continue
    print(f"  Branch ({fb[:20]},{tb[:20]}) phases={phases}:")
    for ph in phases:
        for q in phases:
            ang_ph = I_ang.get((t, fb, tb, ph), None)
            ang_q  = I_ang.get((t, fb, tb, q),  None)
            if ang_ph is None or ang_q is None:
                print(f"    [{ph},{q}] MISSING ANGLE")
                continue
            diff = ang_ph - ang_q
            rval = r[f'{ph}{q}'].get((fb, tb), 0)
            xval = x[f'{ph}{q}'].get((fb, tb), 0)
            term = rval * math.cos(diff) + xval * math.sin(diff)
            print(f"    [{ph},{q}]: r={rval:.6f}  x={xval:.6f}  "
                  f"ang_diff={np.degrees(diff):.1f}°  "
                  f"r*cos+x*sin={term:.6f}")

print()
print("=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
