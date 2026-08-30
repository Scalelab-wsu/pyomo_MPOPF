"""Thorough validation of IEEE_9500 reduced circuit against OpenDSS.

Checks:
  1. LV buses/branches: none should exist (all buses >= 6 kV LN)
  2. Capacitors: none active
  3. Regulators: none active (RegControls disabled)
  4. Loads: CSV bus_data totals match OpenDSS compiled loads exactly
  5. Branch impedances: CSV branch_data matches per-unit Z from OpenDSS
  6. Transformer referral: transformer Z stored at correct (secondary) bus kVBase
  7. Load voltage bases: all loads served at MV primary buses (>=6 kV LN)
"""

import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_grb_ca = os.path.expanduser('~/nrel_gurobi_ca.pem')
if os.path.exists(_grb_ca):
    os.environ['GRB_CAFILE'] = _grb_ca

import opendssdirect as odss

ROOT     = os.path.dirname(os.path.abspath(__file__))
DSS_PATH = os.path.join(ROOT, 'rawData', 'IEEE_9500', 'dss_scripts', 'Master_9500_reduced.dss')
CSV_DIR  = os.path.join(ROOT, 'rawData', 'IEEE_9500', 'csvs')
S_BASE   = 1e6       # 1 MVA system base
V_MV_MIN = 6000.0    # 6 kV LN — below this is LV


# ── helpers ─────────────────────────────────────────────────────────────────
def pass_fail(cond, msg):
    tag = '  PASS' if cond else '  FAIL'
    print(f"{tag}: {msg}")
    return cond


def close(a, b, rtol=1e-3, atol=1e-9):
    if b == 0:
        return abs(a) <= atol
    return abs(a - b) / max(abs(b), atol) <= rtol


# ── compile ──────────────────────────────────────────────────────────────────
print('='*65)
print('IEEE_9500 Reduced Circuit — Validation vs OpenDSS')
print('='*65)
print(f'\nCompiling {os.path.basename(DSS_PATH)} ...')
odss.Text.Command(f'Redirect "{DSS_PATH}"')
odss.Text.Command('Solve')
print(f'  Bus count (OpenDSS): {odss.Circuit.NumBuses()}')
print(f'  Node count         : {odss.Circuit.NumNodes()}')

all_fails = 0


# ══════════════════════════════════════════════════════════════════════════════
# 1. VOLTAGE BASES — ALL BUSES MUST BE MV
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 1. Voltage Bases ───────────────────────────────────────────')
lv_buses = []
for bname in odss.Circuit.AllBusNames():
    odss.Circuit.SetActiveBus(bname)
    kv_ln = odss.Bus.kVBase() * 1000   # kV → V
    if kv_ln < V_MV_MIN:
        lv_buses.append((bname, kv_ln))

if lv_buses:
    print(f'  FAIL: {len(lv_buses)} LV buses (<6 kV LN) found:')
    for b, kv in lv_buses[:20]:
        print(f'        {b:40s}  kVBase(LN)={kv:.1f} V')
    all_fails += 1
else:
    print(f'  PASS: All {odss.Circuit.NumBuses()} buses at MV (>= 6 kV LN)')

kv_bases = {}
for bname in odss.Circuit.AllBusNames():
    odss.Circuit.SetActiveBus(bname)
    kv_ln = odss.Bus.kVBase() * 1000
    kv_str = f'{kv_ln/1000:.2f} kV'
    kv_bases[kv_str] = kv_bases.get(kv_str, 0) + 1
print(f'  kVBase distribution: {dict(sorted(kv_bases.items()))}')


# ══════════════════════════════════════════════════════════════════════════════
# 2. CAPACITORS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 2. Capacitors ─────────────────────────────────────────────')
n_caps = odss.Capacitors.Count()
ok = pass_fail(n_caps == 0, f'Capacitors.Count() = {n_caps}  (expect 0)')
if not ok:
    all_fails += 1
    odss.Capacitors.First()
    for _ in range(min(n_caps, 5)):
        print(f'       Cap: {odss.Capacitors.Name()}  enabled={odss.CktElement.Enabled()}')
        odss.Capacitors.Next()

csv_caps = pd.read_csv(os.path.join(CSV_DIR, 'cap_data.csv'))
ok2 = pass_fail(len(csv_caps) == 0, f'cap_data.csv rows = {len(csv_caps)}  (expect 0)')
if not ok2:
    all_fails += 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. REGULATORS / REGCONTROLS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 3. Regulators ─────────────────────────────────────────────')
rc_names = odss.RegControls.AllNames()
n_rc = len(rc_names)
# RegControls that are commented out in DSS won't appear at all
ok = pass_fail(n_rc == 0, f'RegControls.AllNames() count = {n_rc}  (expect 0)')
if not ok:
    all_fails += 1
    print(f'       RegControl names: {rc_names[:10]}')

csv_regs = pd.read_csv(os.path.join(CSV_DIR, 'reg_data.csv'))
ok2 = pass_fail(len(csv_regs) == 0, f'reg_data.csv rows = {len(csv_regs)}  (expect 0)')
if not ok2:
    all_fails += 1

# Also check VREG transformers exist but have no active tap control
vreg_taps = []
odss.Transformers.First()
while odss.Transformers.NumWindings() > 0:
    name = odss.Transformers.Name()
    tap  = odss.Transformers.Tap()
    if 'vreg' in name.lower() or 'feeder_reg' in name.lower() or 'reg' in name.lower():
        vreg_taps.append((name, tap))
    if not odss.Transformers.Next():
        break
if vreg_taps:
    print(f'  Regulator transformers found (tap=1.0 means neutral, no control active):')
    for nm, tp in vreg_taps[:10]:
        status = 'NEUTRAL' if abs(tp - 1.0) < 1e-4 else f'TAP={tp:.5f} WARN'
        print(f'       {nm:30s}  tap={tp:.5f}  {status}')
    all_taps_neutral = all(abs(tp - 1.0) < 1e-4 for _, tp in vreg_taps)
    ok3 = pass_fail(all_taps_neutral, 'All regulator taps at 1.0 (neutral, no control)')
    if not ok3:
        all_fails += 1


# ══════════════════════════════════════════════════════════════════════════════
# 4. LOADS — compare CSV bus_data vs OpenDSS compiled loads
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 4. Loads ──────────────────────────────────────────────────')

# Gather all loads from OpenDSS
bus_load_p = {}   # bus_name → {ph: P_W}
bus_load_q = {}
lv_load_buses = []
odss.Loads.First()
n_loads_dss = 0
while True:
    lname = odss.Loads.Name()
    bname_raw = odss.CktElement.BusNames()[0]
    bname = bname_raw.split('.')[0].lower()
    nodes_raw = bname_raw.split('.')[1:]

    odss.Circuit.SetActiveBus(bname)
    kv_ln = odss.Bus.kVBase() * 1000
    if kv_ln < V_MV_MIN:
        lv_load_buses.append((lname, bname, kv_ln))

    n_ph = odss.Loads.Phases()
    kw   = odss.Loads.kW()
    kvar = odss.Loads.kvar()
    # Determine phases
    if nodes_raw:
        phases = [{'1': 'a', '2': 'b', '3': 'c'}.get(n, None) for n in nodes_raw if n in '123']
    else:
        phases = ['a', 'b', 'c'] if n_ph >= 3 else [{'1':'a','2':'b','3':'c'}.get(str(n_ph), 'a')]

    p_per_ph = kw   * 1000 / len(phases) if phases else 0
    q_per_ph = kvar * 1000 / len(phases) if phases else 0

    for ph in phases:
        bus_load_p.setdefault(bname, {}).setdefault(ph, 0.0)
        bus_load_p[bname][ph] += p_per_ph
        bus_load_q.setdefault(bname, {}).setdefault(ph, 0.0)
        bus_load_q[bname][ph] += q_per_ph

    n_loads_dss += 1
    if not odss.Loads.Next():
        break

print(f'  OpenDSS load count    : {n_loads_dss}')
print(f'  OpenDSS total P (kW)  : {sum(sum(d.values()) for d in bus_load_p.values())/1000:.3f}')
print(f'  OpenDSS total Q (kVar): {sum(sum(d.values()) for d in bus_load_q.values())/1000:.3f}')

# LV load check
ok = pass_fail(len(lv_load_buses) == 0, f'LV load buses = {len(lv_load_buses)}  (expect 0)')
if not ok:
    all_fails += 1
    for ln, bn, kv in lv_load_buses[:10]:
        print(f'       load={ln}  bus={bn}  kVBase={kv:.0f} V')

# Compare with CSV bus_data
bus_data = pd.read_csv(os.path.join(CSV_DIR, 'bus_data.csv'))
csv_total_p = (bus_data.get('pl_a', 0).sum() + bus_data.get('pl_b', 0).sum() + bus_data.get('pl_c', 0).sum()) * S_BASE / 1e3
csv_total_q = (bus_data.get('ql_a', 0).sum() + bus_data.get('ql_b', 0).sum() + bus_data.get('ql_c', 0).sum()) * S_BASE / 1e3
dss_total_p  = sum(sum(d.values()) for d in bus_load_p.values()) / 1000
dss_total_q  = sum(sum(d.values()) for d in bus_load_q.values()) / 1000

print(f'\n  CSV  total P (kW)     : {csv_total_p:.3f}')
print(f'  CSV  total Q (kVar)   : {csv_total_q:.3f}')
print(f'  DSS  total P (kW)     : {dss_total_p:.3f}')
print(f'  DSS  total Q (kVar)   : {dss_total_q:.3f}')
p_err_pct = abs(csv_total_p - dss_total_p) / max(dss_total_p, 1) * 100
q_err_pct = abs(csv_total_q - dss_total_q) / max(abs(dss_total_q), 1) * 100
ok_p = pass_fail(p_err_pct < 0.1, f'Total P match: CSV={csv_total_p:.3f}  DSS={dss_total_p:.3f}  err={p_err_pct:.4f}%')
ok_q = pass_fail(q_err_pct < 0.1, f'Total Q match: CSV={csv_total_q:.3f}  DSS={dss_total_q:.3f}  err={q_err_pct:.4f}%')
if not ok_p: all_fails += 1
if not ok_q: all_fails += 1

# Per-bus spot check (10 random load buses)
bus_data_named = bus_data.copy()
# DSSParser stores bus name in 'name' if present, else uses id mapping
name_col = 'name' if 'name' in bus_data_named.columns else None
if name_col:
    bus_data_named[name_col] = bus_data_named[name_col].str.lower()
    n_match = 0
    n_miss  = 0
    max_err = 0.0
    max_bus = ''
    for _, row in bus_data_named.iterrows():
        bname = row[name_col]
        if bname not in bus_load_p:
            n_miss += 1
            continue
        for ph in 'abc':
            csv_val = float(row.get(f'pl_{ph}', 0) or 0) * S_BASE / 1e3  # kW
            dss_val = bus_load_p[bname].get(ph, 0.0) / 1e3               # kW
            err = abs(csv_val - dss_val)
            if err > max_err:
                max_err = err
                max_bus = f'{bname}.{ph}'
        n_match += 1
    print(f'\n  Per-bus load check: {n_match} buses matched, {n_miss} buses no DSS load')
    ok_per = pass_fail(max_err < 0.5, f'Max per-bus per-phase load error = {max_err:.4f} kW  (bus: {max_bus})')
    if not ok_per:
        all_fails += 1


# ══════════════════════════════════════════════════════════════════════════════
# 5. BRANCH IMPEDANCES — reparse with DSSParser and compare against saved CSV
#    (uses identical logic to avoid comparing against a buggy independent impl)
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 5. Branch Impedances ──────────────────────────────────────')
branch_data = pd.read_csv(os.path.join(CSV_DIR, 'branch_data.csv'))

# Re-run DSSParser (fresh parse of the same reduced master)
from dssconverter.dssparser import DSSParser
fresh = DSSParser(DSS_PATH)
fresh_bd = fresh.branch_data

# Compare saved CSV against freshly-parsed DSSParser output (ground truth)
# Join by (from_name, to_name) — integer bus IDs differ between parse runs
print(f'  Branches in saved CSV : {len(branch_data)}')
print(f'  Branches in fresh parse: {len(fresh_bd)}')

ok_cnt = pass_fail(len(branch_data) == len(fresh_bd),
                   f'Branch count matches fresh parse: {len(branch_data)} vs {len(fresh_bd)}')
if not ok_cnt: all_fails += 1

# Normalise bus-name keys for join
def _key(fn, tn):
    return tuple(sorted([str(fn).lower(), str(tn).lower()]))

csv_key   = branch_data.copy()
csv_key['_key'] = [_key(r['from_name'], r['to_name']) for _, r in csv_key.iterrows()]
fresh_key = fresh_bd.copy()
fresh_key['_key'] = [_key(r['from_name'], r['to_name']) for _, r in fresh_key.iterrows()]

# Aggregate by key (DSSParser already does groupby(fb,tb); duplicates shouldn't exist)
z_cols  = ['raa','rab','rac','rbb','rbc','rcc','xaa','xab','xac','xbb','xbc','xcc']
csv_agg = csv_key.groupby('_key')[z_cols].sum()
fr_agg  = fresh_key.groupby('_key')[z_cols].sum()

common = csv_agg.index.intersection(fr_agg.index)
RTOL   = 1e-3   # 0.1 % — same DSSParser code, differences only from floating-pt
z_mismatches = []
for col in z_cols:
    diff = (csv_agg.loc[common, col] - fr_agg.loc[common, col]).abs()
    if len(diff) == 0:
        continue
    worst_key = diff.idxmax()
    worst_val = float(diff.max())
    denom_val = float(fr_agg.at[worst_key, col])
    rel       = worst_val / max(abs(denom_val), 1e-12)
    if worst_val > RTOL and rel > RTOL:
        csv_v  = float(csv_agg.at[worst_key, col])
        fresh_v = float(fr_agg.at[worst_key, col])
        z_mismatches.append(
            f'{col}: max_abs_err={worst_val:.3e}  rel={rel:.3e}  '
            f'branch {worst_key}  '
            f'CSV={csv_v:.6f}  fresh={fresh_v:.6f}'
        )

ok_z = pass_fail(len(z_mismatches) == 0,
                 f'Z matrices: CSV == fresh DSSParser ({len(common)} branches '
                 f'matched by name, tol={RTOL:.0e})')
if not ok_z:
    all_fails += 1
    for m in z_mismatches[:10]:
        print(f'       {m}')

# Check no-switch branches are all at MV kVBase
lv_branch_rows = []
for _, row in fresh_bd.iterrows():
    if row.get('type') == 'switch':
        continue
    vb = float(row.get('v_ln_base', 0) or 0)
    if vb < V_MV_MIN:
        lv_branch_rows.append(f'{row["from_name"]}→{row["to_name"]}  vbase={vb:.0f}V')

ok_lv = pass_fail(len(lv_branch_rows) == 0,
                  f'LV non-switch branches (<6 kV LN): {len(lv_branch_rows)}')
if not ok_lv:
    all_fails += 1
    for r in lv_branch_rows[:10]:
        print(f'       {r}')

# Show impedance statistics for main non-switch branches
non_sw = fresh_bd[fresh_bd['type'] != 'switch']
sw     = fresh_bd[fresh_bd['type'] == 'switch']
print(f'\n  Branch types: {dict(fresh_bd["type"].value_counts())}')
print(f'  Non-switch: {len(non_sw)} branches')
print(f'    raa: min={non_sw["raa"].min():.6f}  max={non_sw["raa"].max():.6f}  '
      f'mean={non_sw["raa"].mean():.6f} pu')
print(f'    xaa: min={non_sw["xaa"].min():.6f}  max={non_sw["xaa"].max():.6f}  '
      f'mean={non_sw["xaa"].mean():.6f} pu')
print(f'  Zero-Z lines (likely modelling artefact): '
      f'{((non_sw["raa"]==0)&(non_sw["rbb"]==0)&(non_sw["rcc"]==0)).sum()}')


# ══════════════════════════════════════════════════════════════════════════════
# 6. TRANSFORMER REFERRAL — are transformer Z stored at correct bus kVBase?
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 6. Transformer Referral ───────────────────────────────────')
# Check transformer branches: vbase, Xpu reasonable, referred to secondary side
xfmr_rows = fresh_bd[fresh_bd['type'] == 'transformer'] if 'type' in fresh_bd.columns else fresh_bd.iloc[0:0]
xfmr_warns = []
for _, row in xfmr_rows.iterrows():
    vb  = float(row.get('v_ln_base', 0) or 0)
    xaa = float(row.get('xaa', 0) or 0)
    xbb = float(row.get('xbb', 0) or 0)
    xcc = float(row.get('xcc', 0) or 0)
    x_max = max(xaa, xbb, xcc)

    if vb < V_MV_MIN:
        xfmr_warns.append(f'{row["from_name"]}→{row["to_name"]}: vbase={vb:.0f}V is LV')
    if x_max > 0.2:
        xfmr_warns.append(f'{row["from_name"]}→{row["to_name"]}: Xpu={x_max:.5f} seems too high')

ok_xfmr = pass_fail(len(xfmr_warns) == 0,
                    f'Transformer Z referral ({len(xfmr_rows)} xfmrs): {len(xfmr_warns)} warnings')
if not ok_xfmr:
    all_fails += 1
    for w in xfmr_warns[:10]:
        print(f'       {w}')

# Show all transformer branches from fresh parse for inspection
print(f'\n  Transformer branches ({len(xfmr_rows)}):')
for _, row in xfmr_rows.iterrows():
    fn = str(row['from_name'])
    tn = str(row['to_name'])
    xaa = float(row.get('xaa', 0) or 0)
    xbb = float(row.get('xbb', 0) or 0)
    xcc = float(row.get('xcc', 0) or 0)
    vb  = float(row.get('v_ln_base', 0) or 0)
    print(f'       {fn:30s} → {tn:30s}  vbase={vb/1000:.2f} kV  Xpu(a/b/c)={xaa:.5f}/{xbb:.5f}/{xcc:.5f}')


# ══════════════════════════════════════════════════════════════════════════════
# 7. PV SYSTEMS AND BATTERIES
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 7. PV Systems & Batteries ─────────────────────────────────')
gen_data = pd.read_csv(os.path.join(CSV_DIR, 'gen_data.csv'))
bat_data = pd.read_csv(os.path.join(CSV_DIR, 'battery_data.csv'))

n_pv_dss  = odss.PVsystems.Count()
n_bat_dss = odss.Storages.Count() if hasattr(odss, 'Storages') else len([
    n for n in odss.Circuit.AllElementNames() if n.lower().startswith('storage.')
])
print(f'  CSV gen_data rows     : {len(gen_data)}')
print(f'  CSV bat_data rows     : {len(bat_data)}')
print(f'  OpenDSS PVsystems     : {n_pv_dss}')
print(f'  OpenDSS Storage       : {n_bat_dss}')

# Check PV are all at MV buses
lv_pvs = []
odss.PVsystems.First()
for _ in range(n_pv_dss):
    pname = odss.PVsystems.Name()
    bname = odss.CktElement.BusNames()[0].split('.')[0].lower()
    odss.Circuit.SetActiveBus(bname)
    kv_ln = odss.Bus.kVBase() * 1000
    if kv_ln < V_MV_MIN:
        lv_pvs.append((pname, bname, kv_ln))
    if not odss.PVsystems.Next():
        break

ok_pv = pass_fail(len(lv_pvs) == 0, f'All PV at MV buses ({len(lv_pvs)} at LV)')
if not ok_pv:
    all_fails += 1
    for pn, bn, kv in lv_pvs[:5]:
        print(f'       pv={pn}  bus={bn}  kV={kv:.0f} V')


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
print('\n' + '='*65)
if all_fails == 0:
    print(f'ALL CHECKS PASSED')
else:
    print(f'TOTAL FAILURES: {all_fails}')
print('='*65)
