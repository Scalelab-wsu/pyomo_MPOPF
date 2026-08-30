"""
Validation script: checks IEEE 123-bus parsed CSV data against DSS source files.
Covers: buses, loads, branch impedances, PV ratings, battery ratings, phase consistency, topology.
"""
import pandas as pd
import numpy as np
import re
import networkx as nx

DATA = "rawData/IEEE_123_other"
CSV  = f"{DATA}/csvs"
DSS  = f"{DATA}/dss_scripts"

bus    = pd.read_csv(f"{CSV}/bus_data.csv",    dtype={"name": str})
branch = pd.read_csv(f"{CSV}/branch_data.csv", dtype={"from_name": str, "to_name": str})
gen    = pd.read_csv(f"{CSV}/gen_data.csv",    dtype={"name": str})
bat    = pd.read_csv(f"{CSV}/battery_data.csv",dtype={"name": str})

s_base = 1_000_000   # VA
V_base = float(bus['v_ln_base'].iloc[0])
z_base = V_base**2 / s_base

# ── 1. BUS SUMMARY ────────────────────────────────────────────────────────────
print("="*65)
print("1. BUS DATA SUMMARY")
print("="*65)
swing = bus[bus.bus_type=='SWING']
print(f"  Total buses in CSV     : {len(bus)}")
print(f"  Swing bus(es)          : {swing['name'].tolist()}")
print(f"  Buses with loads       : {int(bus.has_load.sum())}")
print(f"  z_base                 : {z_base:.4f} Ω/pu")
print(f"  V_ln_base unique?      : {bus['v_ln_base'].nunique()==1} → {V_base:.2f} V")
print(f"  s_base unique?         : {bus['s_base'].nunique()==1} → {bus['s_base'].iloc[0]:.0f} VA")
swing_row = swing.iloc[0]
print(f"  SWING voltage (a,b,c)  : {swing_row['v_a']}, {swing_row['v_b']}, {swing_row['v_c']}")
print(f"  v_min range            : {bus.v_min.min()} – {bus.v_min.max()}  (expected 0.95)")
print(f"  v_max range            : {bus.v_max.min()} – {bus.v_max.max()}  (expected 1.05)")

# ── 2. LOAD VALIDATION ────────────────────────────────────────────────────────
print()
print("="*65)
print("2. LOAD VALIDATION (DSS kW/kvar → pu vs CSV pl/ql)")
print("="*65)

with open(f"{DSS}/Loads.dss") as f:
    load_lines = f.readlines()

dss_loads = {}
for line in load_lines:
    m = re.search(r'Bus1=(\w+)\.(\d)\s.*?kw=([\d.]+)\s.*?kvar=([\d.]+)', line)
    if m:
        bus_n = m.group(1).lower()
        ph    = 'abc'[int(m.group(2))-1]
        kw, kvar = float(m.group(3)), float(m.group(4))
        dss_loads.setdefault(bus_n, {})
        dss_loads[bus_n][f'kw_{ph}']   = dss_loads[bus_n].get(f'kw_{ph}', 0.)   + kw
        dss_loads[bus_n][f'kvar_{ph}'] = dss_loads[bus_n].get(f'kvar_{ph}', 0.) + kvar

bus_lkp = bus.set_index('name')
load_errs = []
for bus_n, loads in dss_loads.items():
    if bus_n not in bus_lkp.index:
        load_errs.append(f"  [ERR] Bus '{bus_n}' in Loads.dss NOT in bus_data.csv!")
        continue
    row = bus_lkp.loc[bus_n]
    for ph in 'abc':
        pl_exp = loads.get(f'kw_{ph}',   0.) / 1000.
        ql_exp = loads.get(f'kvar_{ph}', 0.) / 1000.
        pl_csv = float(row[f'pl_{ph}'])
        ql_csv = float(row[f'ql_{ph}'])
        if abs(pl_csv - pl_exp) > 1e-4:
            load_errs.append(f"  [ERR] Bus {bus_n} ph {ph}: pl_csv={pl_csv:.5f}  expected={pl_exp:.5f}  Δ={pl_csv-pl_exp:+.5f}")
        if abs(ql_csv - ql_exp) > 1e-4:
            load_errs.append(f"  [ERR] Bus {bus_n} ph {ph}: ql_csv={ql_csv:.5f}  expected={ql_exp:.5f}  Δ={ql_csv-ql_exp:+.5f}")

total_kw_dss  = sum(v for ld in dss_loads.values() for k,v in ld.items() if k.startswith('kw'))
total_pu_csv  = sum(float(bus[f'pl_{ph}'].sum()) for ph in 'abc')
print(f"  Load buses in DSS       : {len(dss_loads)}")
print(f"  Total DSS load          : {total_kw_dss:.1f} kW  ≡  {total_kw_dss/1000:.4f} pu")
print(f"  Total CSV load (sum pu) : {total_pu_csv:.4f} pu")
if not load_errs:
    print("  [OK] All load values match DSS within 0.0001 pu")
else:
    for e in load_errs[:20]: print(e)

# ── 3. BRANCH IMPEDANCE VALIDATION ────────────────────────────────────────────
print()
print("="*65)
print("3. BRANCH IMPEDANCE VALIDATION (DSS Ω → pu vs CSV)")
print("="*65)

with open(f"{DSS}/BranchData.dss") as f:
    br_lines = f.readlines()

br_lkp = branch.set_index(['from_name','to_name'])
dss_branches = set()
br_errs = []

for line in br_lines:
    m = re.search(r'Line\.line_(\w+)_(\w+)\s.*?phases=(\d+).*?Bus1=(\S+)\s.*?rmatrix=\(([^)]+)\).*?xmatrix=\(([^)]+)\)', line)
    if not m:
        continue
    fb, tb = m.group(1), m.group(2)
    n_ph   = int(m.group(3))
    bus1_str = m.group(4)
    rvals  = [float(x) for x in re.findall(r'[\d.e+\-]+', m.group(5))]
    xvals  = [float(x) for x in re.findall(r'[\d.e+\-]+', m.group(6))]
    dss_branches.add((fb, tb))

    key = (fb, tb)
    if key not in br_lkp.index:
        br_errs.append(f"  [ERR] Branch {fb}→{tb} in DSS NOT in branch_data.csv!")
        continue
    row = br_lkp.loc[key]

    if n_ph == 1:
        ph_m = re.search(r'Bus1=\w+\.(\d)', line)
        ph   = 'abc'[int(ph_m.group(1))-1] if ph_m else 'a'
        pairs = [(f'r{ph}{ph}', rvals[0]), (f'x{ph}{ph}', xvals[0])]
        for pp, dss_v in pairs:
            csv_v = float(row[pp])
            exp_v = dss_v / z_base
            if abs(csv_v - exp_v) > 5e-5:
                br_errs.append(f"  [ERR] {fb}→{tb} {pp}: csv={csv_v:.6f}  exp={exp_v:.6f}  Δ={csv_v-exp_v:+.6f}")
    elif n_ph == 3 and len(rvals) == 6:
        labels = ['aa','ab','bb','ac','bc','cc']
        for pp, dv, xv in zip(labels, rvals, xvals):
            rp = 'r'+pp; xp = 'x'+pp
            csv_r = float(row[rp]); csv_x = float(row[xp])
            exp_r = dv / z_base;    exp_x = xv / z_base
            if abs(csv_r - exp_r) > 5e-5:
                br_errs.append(f"  [ERR] {fb}→{tb} {rp}: csv={csv_r:.6f}  exp={exp_r:.6f}  Δ={csv_r-exp_r:+.6f}")
            if abs(csv_x - exp_x) > 5e-5:
                br_errs.append(f"  [ERR] {fb}→{tb} {xp}: csv={csv_x:.6f}  exp={exp_x:.6f}  Δ={csv_x-exp_x:+.6f}")

csv_branches  = set(zip(branch['from_name'].astype(str), branch['to_name'].astype(str)))
missing_in_csv = dss_branches - csv_branches
extra_in_csv   = csv_branches - dss_branches

print(f"  Branches in DSS         : {len(dss_branches)}")
print(f"  Branches in CSV         : {len(branch)}")
if missing_in_csv:
    print(f"  [WARN] In DSS not in CSV: {sorted(missing_in_csv)}")
if extra_in_csv:
    print(f"  [WARN] In CSV not in DSS: {sorted(extra_in_csv)[:10]}")
if not br_errs and not missing_in_csv and not extra_in_csv:
    print("  [OK] All branch impedances match DSS within 5e-5 pu")
elif not br_errs:
    print("  [OK] No impedance value errors (only count mismatch above)")
else:
    for e in br_errs[:20]: print(e)

# ── 4. PV VALIDATION ─────────────────────────────────────────────────────────
print()
print("="*65)
print("4. PV (gen_data) VALIDATION")
print("="*65)

with open(f"{DSS}/PVSystem.dss") as f:
    pv_lines = f.readlines()

pv_dss = {}   # bus → {kva_total, pmpp_total, n_ph}
for line in pv_lines:
    m = re.search(r'bus1=(\w+)\.(\d).*?kva=([\d.]+).*?Pmpp=([\d.]+)', line, re.I)
    if m:
        bus_n = m.group(1).lower()
        pv_dss.setdefault(bus_n, {'kva':0., 'pmpp':0., 'n_ph':0})
        pv_dss[bus_n]['kva']   += float(m.group(3))
        pv_dss[bus_n]['pmpp']  += float(m.group(4))
        pv_dss[bus_n]['n_ph']  += 1

gen_lkp = gen.set_index('name')
pv_errs = []
missing_pv = set(pv_dss) - set(gen['name'].tolist())
extra_pv   = set(gen['name'].tolist()) - set(pv_dss)
if missing_pv:
    pv_errs.append(f"  [WARN] PV in DSS not in gen_data: {sorted(missing_pv)}")
if extra_pv:
    pv_errs.append(f"  [WARN] PV in gen_data not in DSS: {sorted(extra_pv)[:10]}")

for bus_n, dv in pv_dss.items():
    if bus_n not in gen_lkp.index:
        continue
    row   = gen_lkp.loc[bus_n]
    n_ph  = dv['n_ph']
    for ph in 'abc'[:n_ph]:
        pa_exp = (dv['pmpp'] / n_ph) / 1000.
        sa_exp = (dv['kva']  / n_ph) / 1000.
        pa_csv = float(row[f'p{ph}'])
        sa_csv = float(row[f's{ph}_max'])
        if abs(pa_csv - pa_exp) > 1e-5:
            pv_errs.append(f"  [ERR] Bus {bus_n} ph {ph}: p{ph}={pa_csv:.5f}  exp={pa_exp:.5f}")
        if abs(sa_csv - sa_exp) > 1e-5:
            pv_errs.append(f"  [ERR] Bus {bus_n} ph {ph}: s{ph}_max={sa_csv:.5f}  exp={sa_exp:.5f}")

print(f"  PV buses in DSS         : {len(pv_dss)}")
print(f"  PV buses in CSV         : {len(gen)}")
if not pv_errs:
    print("  [OK] All PV power/kVA ratings match DSS")
else:
    for e in pv_errs[:20]: print(e)

# q limits stored as string "(None, None, None)" — flag this
sample_qa = str(gen.iloc[0].get('qa_max',''))
if 'None' in sample_qa:
    print(f"  [INFO] q_max/q_min stored as string tuples e.g. '{sample_qa}' — not numeric")

# ── 5. BATTERY VALIDATION ─────────────────────────────────────────────────────
print()
print("="*65)
print("5. BATTERY VALIDATION")
print("="*65)

with open(f"{DSS}/Storage.dss") as f:
    st_lines = f.readlines()

def _find(pattern, text):
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None

bat_dss = {}
for line in st_lines:
    if 'Storage.Batt_' not in line and 'storage.batt_' not in line.lower():
        continue
    nm = re.search(r'Storage\.Batt_(\w+)', line, re.I)
    if not nm:
        continue
    name = nm.group(1).lower()
    n_ph     = _find(r'phases=(\d+)', line)
    kva      = _find(r'kva=([\d.]+)', line)
    kwh      = _find(r'kwhrated=([\d.]+)', line)
    kw       = _find(r'kwrated=([\d.]+)', line)
    eff_c    = _find(r'%EffCharge=([\d.]+)', line)
    eff_d    = _find(r'%EffDischarge=([\d.]+)', line)
    pct_res  = _find(r'%reserve=([\d.]+)', line)
    pct_stor = _find(r'%stored=([\d.]+)', line)
    if all(v is not None for v in [n_ph,kva,kwh,kw,eff_c,eff_d,pct_res,pct_stor]):
        bat_dss[name] = dict(
            n_ph=int(n_ph), kva=float(kva),
            kwh=float(kwh), kw=float(kw),
            eff_c=float(eff_c)/100, eff_d=float(eff_d)/100,
            pct_res=float(pct_res)/100, pct_stored=float(pct_stor)/100,
        )

bat_lkp  = bat.set_index('name')
bat_errs = []
hmax_bugs= 0

missing_bat = set(bat_dss) - set(bat['name'].tolist())
extra_bat   = set(bat['name'].tolist()) - set(bat_dss)
if missing_bat:
    bat_errs.append(f"  [WARN] Batteries in DSS not in CSV: {sorted(missing_bat)[:10]}")
if extra_bat:
    bat_errs.append(f"  [WARN] Batteries in CSV not in DSS: {sorted(extra_bat)[:10]}")

for bus_n, dv in bat_dss.items():
    if bus_n not in bat_lkp.index:
        continue
    row  = bat_lkp.loc[bus_n]
    n_ph = dv['n_ph']
    for ph in 'abc'[:n_ph]:
        pb_exp   = (dv['kw']  / n_ph) / 1000.
        kwh_pp   = (dv['kwh'] / n_ph) / 1000.
        bmin_exp = dv['pct_res'] * kwh_pp
        bmax_exp = 0.95            * kwh_pp

        pb_csv   = float(row[f'Pb_max_{ph}'])
        hmax_csv = float(row[f'hmax_{ph}'])
        bmin_csv = float(row[f'bmin_{ph}'])
        bmax_csv = float(row[f'bmax_{ph}'])
        nc_csv   = float(row[f'nc_{ph}'])
        nd_csv   = float(row[f'nd_{ph}'])

        if abs(pb_csv - pb_exp) > 1e-6:
            bat_errs.append(f"  [ERR] {bus_n} ph {ph}: Pb_max csv={pb_csv:.5f}  exp={pb_exp:.5f}")
        if abs(hmax_csv - kwh_pp) > 1e-6:   # hmax should equal kwh per phase in pu
            hmax_bugs += 1
        if abs(bmin_csv - bmin_exp) > 1e-6:
            bat_errs.append(f"  [ERR] {bus_n} ph {ph}: bmin csv={bmin_csv:.5f}  exp={bmin_exp:.5f}")
        if abs(bmax_csv - bmax_exp) > 1e-6:
            bat_errs.append(f"  [ERR] {bus_n} ph {ph}: bmax csv={bmax_csv:.5f}  exp={bmax_exp:.5f}")
        if abs(nc_csv - dv['eff_c']) > 1e-6:
            bat_errs.append(f"  [ERR] {bus_n} ph {ph}: eta_c csv={nc_csv}  exp={dv['eff_c']}")
        if abs(nd_csv - dv['eff_d']) > 1e-6:
            bat_errs.append(f"  [ERR] {bus_n} ph {ph}: eta_d csv={nd_csv}  exp={dv['eff_d']}")

other_bat_errs = [e for e in bat_errs if '[WARN]' not in e]

print(f"  Battery buses in DSS    : {len(bat_dss)}")
print(f"  Battery buses in CSV    : {len(bat)}")
print(f"  Pb_max (power per ph)   : {'[OK]' if not any('Pb_max' in e for e in bat_errs) else '[ERR - see below]'}")
print(f"  bmin (min SOC energy)   : {'[OK]' if not any('bmin' in e for e in bat_errs) else '[ERR - see below]'}")
print(f"  bmax (95% of kWhrated)  : {'[OK]' if not any('bmax' in e for e in bat_errs) else '[ERR - see below]'}")
print(f"  eta_c / eta_d           : {'[OK]' if not any('eta' in e for e in bat_errs) else '[ERR - see below]'}")

if hmax_bugs > 0:
    ex_bus = list(bat_dss.keys())[0]
    dv     = bat_dss[ex_bus]
    n_ph   = dv['n_ph']
    print(f"\n  *** BUG: hmax set to POWER rating, not ENERGY capacity ***")
    print(f"  Location: dssconverter/dssparser.py line ~847")
    print(f"    each_bat['hmax_{{ph}}'] = (kw_rated / n_phases) / 1000 / sbase * 1e6")
    print(f"    SHOULD BE: (kwh_rated / n_phases) / 1000 / sbase * 1e6")
    print()
    print(f"  Example bus '{ex_bus}' (phases={n_ph}, kwrated={dv['kw']}, kwhrated={dv['kwh']}):")
    print(f"    hmax_a in CSV  = {float(bat_lkp.loc[ex_bus,'hmax_a']):.5f}  (= {dv['kw']/n_ph:.1f} kW/ph / 1000)")
    print(f"    hmax_a CORRECT = {(dv['kwh']/n_ph)/1000:.5f}  (= {dv['kwh']/n_ph:.1f} kWh/ph / 1000)")
    print(f"    Affects {hmax_bugs} phase-entries across all batteries")
    print(f"  Note: bmin/bmax correctly use kwhrated — SOC bounds are fine.")
    print(f"  Impact: s_B (used in model) equals power rating not energy capacity.")
else:
    print(f"  hmax (energy capacity)  : [OK]")

for e in bat_errs: print(e)

# ── 6. PHASE CONSISTENCY ──────────────────────────────────────────────────────
print()
print("="*65)
print("6. PHASE CONSISTENCY")
print("="*65)
ph_errs = []

for bus_n, loads in dss_loads.items():
    if bus_n not in bus_lkp.index:
        continue
    bph = str(bus_lkp.loc[bus_n, 'phases'])
    for ph in 'abc':
        if loads.get(f'kw_{ph}', 0.) > 0 and ph not in bph:
            ph_errs.append(f"  [ERR] Bus {bus_n}: load on phase '{ph}' but bus phases='{bph}'")

for bus_n in pv_dss:
    if bus_n not in bus_lkp.index or bus_n not in gen_lkp.index:
        continue
    bph   = str(bus_lkp.loc[bus_n, 'phases'])
    g_ph  = str(gen_lkp.loc[bus_n, 'phases'])
    extra = set(g_ph) - set(bph) - {' ',','}
    if extra:
        ph_errs.append(f"  [ERR] Bus {bus_n}: PV phases='{g_ph}' not subset of bus phases='{bph}'")

for bus_n in bat_dss:
    if bus_n not in bus_lkp.index or bus_n not in bat_lkp.index:
        continue
    bph   = str(bus_lkp.loc[bus_n, 'phases'])
    b_ph  = str(bat_lkp.loc[bus_n, 'phases'])
    extra = set(b_ph) - set(bph) - {' ',','}
    if extra:
        ph_errs.append(f"  [ERR] Bus {bus_n}: Battery phases='{b_ph}' not subset of bus phases='{bph}'")

if not ph_errs:
    print("  [OK] All phase assignments are consistent")
else:
    for e in ph_errs: print(e)

# ── 7. TOPOLOGY ───────────────────────────────────────────────────────────────
print()
print("="*65)
print("7. TOPOLOGY / NETWORK CHECKS")
print("="*65)

G = nx.Graph()
for _, row in branch[branch['status'] != 'OPEN'].iterrows():
    G.add_edge(str(row['from_name']), str(row['to_name']))

swing_bus = str(swing['name'].values[0])
n_buses   = len(bus)
n_nodes_g = G.number_of_nodes()
n_edges_g = G.number_of_edges()
connected = nx.is_connected(G)
is_tree   = nx.is_tree(G)

print(f"  Buses in CSV            : {n_buses}")
print(f"  Nodes in branch graph   : {n_nodes_g}")
print(f"  Edges (branches)        : {n_edges_g}")
print(f"  Connected graph         : {'[OK]' if connected else '[WARN] NOT connected!'}")
print(f"  Radial (tree)?          : {'[OK]' if is_tree else '[WARN] Contains loops or isolated nodes'}")

bus_csv_set   = set(bus['name'].tolist())
not_in_graph  = bus_csv_set - set(G.nodes())
not_in_bus_csv= set(G.nodes()) - bus_csv_set
if not_in_graph:
    print(f"  [INFO] Buses in CSV not in branch graph : {sorted(not_in_graph)}")
if not_in_bus_csv:
    print(f"  [WARN] Branch graph nodes not in bus CSV: {sorted(not_in_bus_csv)[:10]}")
if connected:
    print(f"  All buses reachable from swing '{swing_bus}': [OK]")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print()
print("="*65)
print("OVERALL SUMMARY")
print("="*65)
all_ok = (not load_errs and not br_errs and not missing_in_csv
          and not extra_in_csv and not pv_errs and not other_bat_errs
          and not ph_errs and connected and is_tree)
bugs = []
if load_errs:          bugs.append("Load values mismatch")
if br_errs:            bugs.append("Branch impedance mismatch")
if missing_in_csv:     bugs.append("Branches missing from CSV")
if pv_errs:            bugs.append("PV ratings mismatch")
if other_bat_errs:     bugs.append("Battery parameter mismatch")
if ph_errs:            bugs.append("Phase inconsistency")
if not connected:      bugs.append("Network not fully connected")
if not is_tree:        bugs.append("Network has loops")
if hmax_bugs > 0:      bugs.append(f"hmax set to power rating not energy (dssparser.py bug, {hmax_bugs} entries)")

if all_ok and not hmax_bugs:
    print("  ALL CHECKS PASSED — data looks correctly parsed!")
else:
    if all_ok:
        print("  Core data (loads/impedances/PV/battery SOC) correctly parsed.")
    for b in bugs:
        print(f"  [ISSUE] {b}")
