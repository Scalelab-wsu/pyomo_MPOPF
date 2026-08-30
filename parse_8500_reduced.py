#!/usr/bin/env python3
"""
parse_8500_reduced.py

Parse the IEEE_8500 DSS feeder and produce a *reduced* circuit that refers
only to the primary (MV) side of the 120/240 V service transformers.

Strategy
--------
1. Compile the full 8500 feeder (with LoadXfmrs.dss re-enabled) so that every
   service transformer and its secondary loads are present.
2. Walk the PDElements to find all 1-phase service transformers
   (primary kV ≈ 7.2, secondary kV ≈ 0.12) and build the mapping
       X_secondary_bus  →  (MV_primary_bus, phase_char)
3. Walk every load at an SX-bus, trace back to its MV primary bus via the
   mapping above, and accumulate (kW, kvar) keyed by (mv_bus, phase_char).
4. Write  Loads_8500_reduced.dss  – single-phase constant-power loads at MV
   primary buses.
5. Write  Master_8500_reduced.dss  – original master with the secondary-side
   redirects commented out and the new loads file redirected in.
6. Run DSSParser on the reduced master and save all CSVs to
   rawData/IEEE_8500/csvs/.

Both reduced DSS files are placed in rawData/IEEE_8500/dss_scripts/ so that
relative-path redirects inside the master (LineCodes2.DSS, Lines.dss, etc.)
continue to resolve correctly.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import opendssdirect as dss

# ── project root & paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dssconverter.dssparser import DSSParser   # noqa: E402 (after path insert)
from dssconverter.savedss   import savedsscsv  # noqa: E402

DSS_DIR     = PROJECT_ROOT / "rawData" / "IEEE_8500" / "dss_scripts"
CSV_DIR     = PROJECT_ROOT / "rawData" / "IEEE_8500" / "csvs"

MASTER          = DSS_DIR / "Master.dss"
MASTER_REDUCED  = DSS_DIR / "Master_8500_reduced.dss"
LOADS_REDUCED   = DSS_DIR / "Loads_8500_reduced.dss"

# ── helpers ─────────────────────────────────────────────────────────────────

def _parse_kVs(kVs_raw: str) -> list[float]:
    """Parse OpenDSS Properties.Value('kVs') → list of floats."""
    return [float(v.strip()) for v in kVs_raw.strip("[]").split(",") if v.strip()]


# ════════════════════════════════════════════════════════════════════════════
# Step 0 – read original Master.dss
# ════════════════════════════════════════════════════════════════════════════
print("=" * 68)
print("IEEE_8500 reduced-circuit parser")
print("=" * 68)

with open(MASTER, "r") as fh:
    master_content = fh.read()

# ════════════════════════════════════════════════════════════════════════════
# Step 1 – compile the existing Master.dss
# (LoadXfmrCodes.dss already defines all service transformers via XfmrCode;
#  LoadXfmrs.dss is the old inline-impedance alternative and stays commented.)
# ════════════════════════════════════════════════════════════════════════════
print("\n[1/6] Compiling existing Master.dss (service transformers via LoadXfmrCodes.dss) ...")

dss.Basic.ClearAll()
dss.Text.Command(f'Redirect "{MASTER}"')
dss.Text.Command("Solve mode=snap")
print("    Solved.")

# ════════════════════════════════════════════════════════════════════════════
# Step 2 – build mapping  X_bus → (mv_primary_bus, phase_char)
# ════════════════════════════════════════════════════════════════════════════
print("\n[2/6] Identifying service transformers ...")

x_to_primary: dict[str, tuple[str, str]] = {}  # x_bus_lower → (mv_bus, ph)

flag = dss.PDElements.First()
while flag:
    # Only process transformers
    element_name_full = dss.CktElement.Name().lower()        # "transformer.tXXX"
    element_type = element_name_full.split(".")[0]

    if element_type != "transformer":
        flag = dss.PDElements.Next()
        continue

    # Read kVs via Properties to avoid the Transformers-API sync bug
    kVs = _parse_kVs(dss.Properties.Value("kVs"))
    if len(kVs) < 2:
        flag = dss.PDElements.Next()
        continue

    kv_primary   = kVs[0]
    kv_secondary = kVs[1]

    # Service transformer: primary ~7.2 kV LN, secondary ~0.12 kV LN
    # (Excludes HV/MV substation ~115→12.47 kV and regulator ~7.2→7.2 kV.)
    if not (abs(kv_primary - 7.2) < 1.5 and abs(kv_secondary - 0.12) < 0.05):
        flag = dss.PDElements.Next()
        continue

    bus_names = dss.CktElement.BusNames()
    if len(bus_names) < 2:
        flag = dss.PDElements.Next()
        continue

    # Winding 1 = primary MV bus, e.g. "L2804253.1"
    # Winding 2 = secondary X-bus, e.g. "X2804253A.1.0"
    primary_bus_full   = bus_names[0]
    secondary_bus_full = bus_names[1]

    primary_bus   = primary_bus_full.split(".")[0].lower()       # "l2804253"
    primary_nodes = primary_bus_full.split(".")[1:]
    phase_char    = (
        "abc"[int(primary_nodes[0]) - 1]
        if primary_nodes and primary_nodes[0].isdigit()
        else "a"
    )

    x_bus = secondary_bus_full.split(".")[0].lower()             # "x2804253a"
    x_to_primary[x_bus] = (primary_bus, phase_char)

    flag = dss.PDElements.Next()

print(f"    Found {len(x_to_primary)} service transformers.")

# ════════════════════════════════════════════════════════════════════════════
# Step 3 – aggregate loads at MV primary buses
# ════════════════════════════════════════════════════════════════════════════
print("\n[3/6] Aggregating loads at MV primary buses ...")

# (mv_bus, phase_char) → [total_kW, total_kvar]
loads_at_primary: dict[tuple[str, str], list[float]] = {}
unmapped: list[str] = []

flag = dss.Loads.First()
while flag:
    load_bus_full = dss.CktElement.BusNames()[0]          # "SX2673305B.1.2"
    load_bus      = load_bus_full.split(".")[0].lower()   # "sx2673305b"
    kw   = dss.Loads.kW()
    kvar = dss.Loads.kvar()

    if load_bus.startswith("sx"):
        # Secondary customer bus → trace through transformer table
        x_bus = "x" + load_bus[2:]                       # "x2673305b"
        if x_bus in x_to_primary:
            mv_bus, ph = x_to_primary[x_bus]
            key = (mv_bus, ph)
            if key not in loads_at_primary:
                loads_at_primary[key] = [0.0, 0.0]
            loads_at_primary[key][0] += kw
            loads_at_primary[key][1] += kvar
        else:
            unmapped.append(load_bus)
    else:
        # Load is already at an MV bus (uncommon in standard 8500 feeder)
        bus_nodes = load_bus_full.split(".")[1:]
        n_phases  = dss.Loads.Phases()
        if not bus_nodes:
            for idx in range(n_phases):
                ph = "abc"[idx]
                key = (load_bus, ph)
                if key not in loads_at_primary:
                    loads_at_primary[key] = [0.0, 0.0]
                loads_at_primary[key][0] += kw / n_phases
                loads_at_primary[key][1] += kvar / n_phases
        else:
            for node_str in bus_nodes:
                if node_str.isdigit() and 1 <= int(node_str) <= 3:
                    ph = "abc"[int(node_str) - 1]
                    key = (load_bus, ph)
                    if key not in loads_at_primary:
                        loads_at_primary[key] = [0.0, 0.0]
                    loads_at_primary[key][0] += kw
                    loads_at_primary[key][1] += kvar

    flag = dss.Loads.Next()

total_kw   = sum(v[0] for v in loads_at_primary.values())
total_kvar = sum(v[1] for v in loads_at_primary.values())
n_buses    = len(set(k[0] for k in loads_at_primary))

print(f"    Aggregated {len(loads_at_primary)} (bus, phase) entries "
      f"across {n_buses} MV buses.")
print(f"    Total load: {total_kw:.2f} kW  /  {total_kvar:.2f} kvar")

if unmapped:
    print(f"    WARNING: {len(unmapped)} SX-loads not found in transformer table "
          f"(first 5: {unmapped[:5]})")

# Collect LN kV for each MV load bus (used in the new loads file)
mv_bus_kv: dict[str, float] = {}
for mv_bus, _ in loads_at_primary:
    if mv_bus not in mv_bus_kv:
        dss.Circuit.SetActiveBus(mv_bus)
        mv_bus_kv[mv_bus] = dss.Bus.kVBase()   # line-to-neutral, kV

# ════════════════════════════════════════════════════════════════════════════
# Step 4 – write  Loads_8500_reduced.dss
# ════════════════════════════════════════════════════════════════════════════
print(f"\n[4/6] Writing {LOADS_REDUCED.name} ...")

phase_to_node = {"a": "1", "b": "2", "c": "3"}
load_lines: list[str] = [
    "! Reduced load file for IEEE_8500 feeder",
    "! All residential loads aggregated at the primary (MV) side of",
    "! 120/240 V service transformers.  Generated by parse_8500_reduced.py.",
    f"! Total: {total_kw:.2f} kW  /  {total_kvar:.2f} kvar",
    "",
]

n_load_entries = 0
for (mv_bus, ph), (kw, kvar) in sorted(loads_at_primary.items()):
    if kw == 0.0 and kvar == 0.0:
        continue
    node   = phase_to_node[ph]
    kv_ln  = mv_bus_kv.get(mv_bus, 7.199)
    lname  = f"red_{mv_bus}_{ph}"
    load_lines.append(
        f"New Load.{lname:<42s}  phases=1  Bus1={mv_bus.upper()}.{node}"
        f"  kv={kv_ln:.4f}  kW={kw:.6f}  kvar={kvar:.6f}  model=1  conn=wye"
    )
    n_load_entries += 1

with open(LOADS_REDUCED, "w") as fh:
    fh.write("\n".join(load_lines) + "\n")

print(f"    {n_load_entries} load entries written.")

# ════════════════════════════════════════════════════════════════════════════
# Step 5 – write  Master_8500_reduced.dss
# ════════════════════════════════════════════════════════════════════════════
print(f"\n[5/6] Writing {MASTER_REDUCED.name} ...")

reduced = master_content

# Comment out triplex line codes (no triplex lines in reduced circuit)
reduced = reduced.replace(
    "Redirect  Triplex_Linecodes.dss",
    "//Redirect  Triplex_Linecodes.dss  ! Not needed: service drops removed",
)

# Keep the "already commented" LoadXfmrs entry but update the comment
reduced = reduced.replace(
    "//Redirect  LoadXfmrs.dss    ! Load Transformers",
    "//Redirect  LoadXfmrs.dss    ! Service transformers excluded (primary network only)",
)

# Comment out LoadXfmrCodes (contains service transformer definitions + codes)
reduced = reduced.replace(
    "Redirect  LoadXfmrCodes.dss  ! Referencing XfmrCodes",
    "//Redirect  LoadXfmrCodes.dss  ! Service transformer definitions excluded",
)

# Comment out triplex service-drop lines
reduced = reduced.replace(
    "Redirect  Triplex_Lines.DSS",
    "//Redirect  Triplex_Lines.DSS  ! Service drop lines removed",
)

# Replace original loads redirect with the reduced loads file
reduced = reduced.replace(
    "Redirect  Loads.dss     ! Balanced Loads",
    "//Redirect  Loads.dss     ! Replaced by reduced loads below\n"
    "Redirect  Loads_8500_reduced.dss  ! Loads aggregated at primary MV buses",
)

# Remove LV voltage bases (no secondary buses in reduced circuit)
reduced = reduced.replace(
    "Set voltagebases=[115, 12.47,  0.48, 0.208]",
    "Set voltagebases=[115, 12.47]  ! LV secondary bases removed",
)

with open(MASTER_REDUCED, "w") as fh:
    fh.write(reduced)

print(f"    Written.")

# ════════════════════════════════════════════════════════════════════════════
# Step 6 – run DSSParser on reduced master, save CSVs
# ════════════════════════════════════════════════════════════════════════════
print("\n[6/6] Running DSSParser on reduced circuit ...")

# Clear previous circuit state before DSSParser compiles the reduced master
dss.Basic.ClearAll()

try:
    parser = DSSParser(str(MASTER_REDUCED))
except Exception as exc:
    print(f"    ERROR in DSSParser: {exc}")
    raise

print(f"    Buses    : {len(parser.bus_names)}")
print(f"    Branches : {len(parser.branch_data)}")
print(f"    Caps     : {len(parser.cap_data)}")
print(f"    Regs     : {len(parser.reg_data)}")
print(f"    Gens/PV  : {len(parser.gen_data)}")

CSV_DIR.mkdir(parents=True, exist_ok=True)
savedsscsv(parser, str(CSV_DIR))

print(f"\nAll CSVs saved to: {CSV_DIR}")
print(f"  branch_data.csv  bus_data.csv  cap_data.csv")
print(f"  gen_data.csv     reg_data.csv  battery_data.csv")


print("\nDone.\n")
print(f"Reduced DSS files in {DSS_DIR}:")
print(f"  {MASTER_REDUCED.name}")
print(f"  {LOADS_REDUCED.name}")
