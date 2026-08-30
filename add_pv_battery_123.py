#!/usr/bin/env python3
"""
add_pv_battery_123.py

Add co-located PV + battery pairs on the IEEE_123 feeder, sized exactly like the
IEEE_9500 / IEEE_8500 setups:

  * PVSystem.dss  - one single-phase PVsystem per load node;
                    pmpp = 40% of that node's load  ->  aggregate PV rating
                    = 40% of the feeder peak load.  kVA = pmpp (matches the
                    9500 convention, q-headroom = sqrt(S^2 - P^2) only at
                    partial irradiance).
  * Storage.dss   - ONE multi-phase 2-hour battery per bus;
                    kWrated  = 40% of the bus load (summed over its phases)
                             ->  aggregate battery power = 40% of peak load;
                    kWhrated = 2 * kWrated  (2-hour battery).

Both files overwrite the existing PVSystem.dss / Storage.dss (Master.dss already
redirects them), then DSSParser is re-run and every CSV in
rawData/IEEE_123/csvs is refreshed.
"""

import re
import sys
from pathlib import Path

import opendssdirect as dss

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dssconverter.dssparser import DSSParser   # noqa: E402
from dssconverter.savedss   import savedsscsv  # noqa: E402

DSS_DIR = PROJECT_ROOT / "rawData" / "IEEE_123" / "dss_scripts"
CSV_DIR = PROJECT_ROOT / "rawData" / "IEEE_123" / "csvs"

LOADS_FILE  = DSS_DIR / "Loads.dss"
MASTER_FILE = DSS_DIR / "Master.dss"
PV_FILE     = DSS_DIR / "PVSystem.dss"
BAT_FILE    = DSS_DIR / "Storage.dss"

KV_LN = 2.4     # single-phase line-to-neutral kV (4.16 kV feeder)
KV_LL = 4.16    # multi-phase line-to-line kV
NODE_PENETRATION = 0.50  # DER placed on the top 50% of load BUSES (by load, desc)
DER_SIZE         = 0.45  # PV & battery each sized at 45% of the node's load
BAT_HOURS        = 2.0   # 2-hour batteries: kWhrated = BAT_HOURS * kWrated

# ============================================================================
# Step 1 - parse Loads.dss to recover (bus, phase, node, kW, kvar)
# ============================================================================
print("=" * 68)
print("IEEE_123  -  DER on top 50% of load buses, sized 45% of node load, 2-hour")
print("=" * 68)

print(f"\n[1/4] Parsing {LOADS_FILE.name} ...")

# Line format (Loads.dss):
# New Load.load_3_a phases=1 Bus1=3.1 conn=wye kv=2.4 kw=40.0 kvar=20.0 ...
_LINE_RE = re.compile(
    r"^New Load\.\S+\s+"
    r"phases=1\s+"
    r"Bus1=(\w+)\.(\d)\s+"      # (bus_name, node)
    r"conn=\w+\s+"
    r"kv=[\d.]+\s+"
    r"kw=([\d.]+)\s+"           # kW
    r"kvar=([\d.]+)",           # kvar
    re.IGNORECASE,
)

# (bus_lower, phase_char, node_int, kW, kvar) aggregated per (bus, node)
node_load: dict[tuple[str, int], list] = {}
with open(LOADS_FILE, "r") as fh:
    for line in fh:
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        bus  = m.group(1).lower()
        node = int(m.group(2))
        kw   = float(m.group(3))
        kvar = float(m.group(4))
        ph   = "abc"[node - 1]
        key  = (bus, node)
        if key in node_load:
            node_load[key][1] += kw
            node_load[key][2] += kvar
        else:
            node_load[key] = [ph, kw, kvar]

# Total load per bus (sum over its phase nodes)
bus_load: dict[str, float] = {}
for (bus, node), (ph, kw, kvar) in node_load.items():
    bus_load[bus] = bus_load.get(bus, 0.0) + kw

# Rank buses by DESCENDING load, select the top NODE_PENETRATION fraction
ranked   = sorted(bus_load, key=lambda b: bus_load[b], reverse=True)
n_sel    = max(1, round(NODE_PENETRATION * len(ranked)))
selected = set(ranked[:n_sel])

# DER placed ONLY on the selected (highest-load) buses
der_entries = [
    (bus, ph, node, kw, kvar)
    for (bus, node), (ph, kw, kvar) in node_load.items()
    if bus in selected
]
peak_load_kw  = sum(bus_load.values())
selected_load = sum(bus_load[b] for b in selected)

print(f"    Total load buses    : {len(bus_load)}")
print(f"    Selected DER buses   : {n_sel} "
      f"({NODE_PENETRATION*100:.0f}% highest-load, descending)")
print(f"    Feeder peak load     : {peak_load_kw:.2f} kW")
print(f"    Load on DER buses    : {selected_load:.2f} kW "
      f"({selected_load/peak_load_kw*100:.1f}% of peak)")
print(f"    DER size per node    : {DER_SIZE*100:.0f}% of node load "
      f"(battery {BAT_HOURS:.0f}-hour)")

# ============================================================================
# Step 2 - write PVSystem.dss (one single-phase PV per load node)
# ============================================================================
print(f"\n[2/4] Writing {PV_FILE.name} ...")

total_pv_kw = sum(e[3] * DER_SIZE for e in der_entries)

pv_lines = [
    "! PV systems for IEEE_123 feeder.",
    f"! {len(der_entries)} single-phase PVsystems on the top "
    f"{NODE_PENETRATION*100:.0f}% highest-load buses.",
    f"! Each pmpp = {DER_SIZE*100:.0f}% of the node load.",
    f"! Feeder peak load: {peak_load_kw:.2f} kW   "
    f"Total installed PV: {total_pv_kw:.2f} kW",
    "! Generated by add_pv_battery_123.py",
    "",
]
for bus, ph, node, kw, _ in der_entries:
    pv_kw = kw * DER_SIZE
    pv_name = f"PV_{bus}_{ph}"
    pv_lines.append(
        f"New PVSystem.{pv_name:<12s} phases=1 bus1={bus.upper()}.{node}"
        f" kv={KV_LN} irradiance=1 kva={pv_kw:.4f} Pmpp={pv_kw:.4f}"
        f" Vmaxpu=1.05 Vminpu=0.95 %cutin=0.1 %cutout=0.1"
    )
with open(PV_FILE, "w") as fh:
    fh.write("\n".join(pv_lines) + "\n")

print(f"    {len(der_entries)} PVsystem entries  |  total capacity = "
      f"{total_pv_kw:.2f} kW ({total_pv_kw/peak_load_kw*100:.1f}% of peak)")

# ============================================================================
# Step 3 - write Storage.dss (ONE multi-phase 2-hour battery per bus)
# ============================================================================
print(f"\n[3/4] Writing {BAT_FILE.name} ...")

# The OPF models ONE battery per bus (P_c/P_d keyed by bus) and splits its net
# power EQUALLY across the bus's phases, so emit ONE multi-phase Storage per bus
# with KWrated = sum of the bus's per-phase battery power.
bus_bat: dict[str, dict] = {}
for bus, ph, node, kw, kvar in der_entries:
    rec = bus_bat.setdefault(bus, {"nodes": set(), "kw": 0.0})
    rec["nodes"].add(node)
    rec["kw"] += kw

total_bat_kw  = sum(r["kw"] * DER_SIZE for r in bus_bat.values())
total_bat_kwh = total_bat_kw * BAT_HOURS

bat_lines = [
    "! Battery storage for IEEE_123 feeder.",
    f"! {len(bus_bat)} {BAT_HOURS:.0f}-hour batteries, ONE (multi-phase) per bus, "
    f"co-located with PV on the top {NODE_PENETRATION*100:.0f}% highest-load buses.",
    f"! KWrated = {DER_SIZE*100:.0f}% of the bus load (summed over its phases); "
    f"Kwhrated = {BAT_HOURS:.0f} * KWrated.",
    f"! Total battery: {total_bat_kw:.2f} kW / {total_bat_kwh:.2f} kWh",
    "! Generated by add_pv_battery_123.py",
    "",
]
for bus, rec in bus_bat.items():
    nodes   = sorted(rec["nodes"])
    n_ph    = len(nodes)
    bat_kw  = rec["kw"] * DER_SIZE
    bat_kwh = bat_kw * BAT_HOURS
    kv      = KV_LL if n_ph > 1 else KV_LN
    bus_ref = ".".join([bus.upper()] + [str(n) for n in nodes])
    bat_name = f"Batt_{bus}"
    bat_lines.append(
        f"New Storage.{bat_name:<10s} phases={n_ph} bus1={bus_ref} kv={kv}"
        f" kva={bat_kw:.4f} kvar=0 %EffCharge=95.0 %EffDischarge=95.0"
        f" Vmaxpu=1.05 Vminpu=0.95 %IdlingKw=0 kwhrated={bat_kwh:.4f}"
        f" kwrated={bat_kw:.4f} %stored=62.5 %reserve=30 DispMode=External"
    )
with open(BAT_FILE, "w") as fh:
    fh.write("\n".join(bat_lines) + "\n")

print(f"    {len(bus_bat)} batteries written  |  total = "
      f"{total_bat_kw:.2f} kW / {total_bat_kwh:.2f} kWh "
      f"({total_bat_kw/peak_load_kw*100:.1f}% of peak)")

# ============================================================================
# Step 4 - re-run DSSParser and refresh all CSVs
# ============================================================================
print(f"\n[4/4] Re-running DSSParser on {MASTER_FILE.name} ...")

dss.Basic.ClearAll()
parser = DSSParser(str(MASTER_FILE))

print(f"    Buses    : {len(parser.bus_names)}")
print(f"    Branches : {len(parser.branch_data)}")
print(f"    Caps     : {len(parser.cap_data)}")
print(f"    Regs     : {len(parser.reg_data)}")
print(f"    Gens/PV  : {len(parser.gen_data)}")
print(f"    Batteries: {len(parser.bat_data)}")

CSV_DIR.mkdir(parents=True, exist_ok=True)
savedsscsv(parser, str(CSV_DIR))

print(f"\nAll CSVs refreshed in: {CSV_DIR}")
print("Done.")
