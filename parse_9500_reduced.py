"""
Parse IEEE 9500-Node feeder to MV-primary-only reduced circuit.

Bases the reduction on Master-unbal-initial-config.dss (canonical original circuit).

Reduction steps:
  1. Filter out 21 LV DER lines/switches from LinesSwitchesGeometry.dss
     → LinesSwitches_9500_noder_geom.dss
  2. Filter out New Transformer.2001-ESS12 (kV=0.48) from EnergyStorage.dss
     → EnergyStorage_9500_noder.dss
  3. Create Master_9500_reduced.dss (based on Master-unbal-initial-config.dss):
     - Use LineGeometry.dss (geometry-based, matches canonical source)
     - Use LinesSwitches_9500_noder_geom.dss (removes 21 LV DER lines/switches)
     - Comment out TriplexLineCodes, LoadXfmrCodes, TriplexLines (secondary removed)
     - Comment out UnbalancedLoads; use Loads_primary.dss (MV-aggregated loads)
     - Comment out Capacitors, CapControls
     - Keep Regulators.dss (RegControls already commented in source files)
     - Exclude Generators.dss  (removes 7 LV DER step-up transformers + inactive gens)
     - Use EnergyStorage_9500_noder.dss  (removes ESS step-up transformer)
     - Use PVSystems_primary.dss (MV primary PV systems)
     - voltagebases=[115, 69, 12.47]  (no 0.48 kV base)
  4. Parse compiled circuit with DSSParser and save CSVs.

Expected result: ~2720 buses, ~2730 branches, 0 LV DER branches,
                 173 PV, 175 batteries, 0 caps, 0 regs.
"""

import re
import sys
import os
from pathlib import Path

# ── paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DSS_DIR = ROOT / "rawData" / "IEEE_9500" / "dss_scripts"
CSV_DIR = ROOT / "rawData" / "IEEE_9500" / "csvs"

# ── DER LV bus pattern: any bus that belongs to the 480V sub-networks ───────
DER_BUS_RE = re.compile(
    r"DER480|DER-\d|-WT\d|-DIES\d|-LNG\d|-MT\d|-ESS\d", re.IGNORECASE
)

def _is_lv_der_line(line: str) -> bool:
    """Return True if a 'New Line.*' definition connects to a LV DER bus."""
    bus1 = re.search(r"bus1=(\S+)", line, re.IGNORECASE)
    bus2 = re.search(r"bus2=(\S+)", line, re.IGNORECASE)
    b1 = bus1.group(1) if bus1 else ""
    b2 = bus2.group(1) if bus2 else ""
    return bool(DER_BUS_RE.search(b1) or DER_BUS_RE.search(b2))


def create_lines_noder():
    """Filter LinesSwitchesLineCodes.dss → LinesSwitches_9500_noder.dss.

    Removes the 21 LV DER lines/switches that connect to 480V sub-networks.
    Uses the linecodes-based file (LinesSwitchesLineCodes.dss) because it has
    ALL tie switches active. The geometry-based file (LinesSwitchesGeometry.dss)
    has most tie switches commented out, which would break the feeder topology.
    """
    src = DSS_DIR / "LinesSwitchesLineCodes.dss"
    dst = DSS_DIR / "LinesSwitches_9500_noder.dss"

    skip_next = False          # True while in a skipped multi-line block
    kept, removed = 0, 0
    out_lines = []

    with src.open() as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.lstrip()

            # Continuation of previous skipped block
            if skip_next and stripped.startswith("~"):
                removed += 1
                continue

            # Any non-continuation resets the skip flag
            skip_next = False

            if re.match(r"(?i)New\s+Line\.", stripped):
                if _is_lv_der_line(stripped):
                    skip_next = True
                    removed += 1
                    continue
                else:
                    kept += 1

            out_lines.append(raw)

    with dst.open("w") as f:
        f.writelines(out_lines)

    print(f"[lines] Kept {kept} line definitions, removed {removed} LV DER lines.")
    print(f"        → {dst}")


def create_energystorage_noder():
    """Filter EnergyStorage.dss → EnergyStorage_9500_noder.dss.

    Removes `New Transformer.2001-ESS12` and its winding lines.
    All other elements (MV batteries Battery3+) are kept.
    """
    src = DSS_DIR / "EnergyStorage.dss"
    dst = DSS_DIR / "EnergyStorage_9500_noder.dss"

    skip_next_continuation = False
    removed_xfmr = False
    out_lines = []

    with src.open() as f:
        for raw in f:
            stripped = raw.lstrip()

            # Skip continuation lines of a skipped transformer block
            if skip_next_continuation and stripped.startswith("~"):
                continue

            skip_next_continuation = False

            # Detect the ESS step-up transformer with 0.48 kV secondary
            if re.match(r"(?i)New\s+Transformer\.", stripped):
                # Check if this is an LV step-up (0.48 kV secondary)
                # We'll look ahead via a flag and inspect the wdg2 lines
                # Simpler: just check for known transformer name pattern
                # The transformer is: New Transformer.2001-ESS12 ... kVA=750 ...
                # It always has kV=0.480 on wdg=2 continuation line.
                # Flag to check — mark and check next ~ lines
                pending = raw
                pending_skip = False
                # We'll buffer and decide when we see the wdg2 continuation
                # Actually: just check inline kV pattern for wdg hints
                # Since the LV kV= appears on the ~ line, peek ahead approach:
                # Simplest: skip by transformer name
                if re.search(r"2001-ESS12", stripped, re.IGNORECASE):
                    skip_next_continuation = True
                    removed_xfmr = True
                    continue  # skip this New Transformer line

            out_lines.append(raw)

    with dst.open("w") as f:
        f.writelines(out_lines)

    print(f"[energy] Removed ESS step-up transformer: {removed_xfmr}")
    print(f"         → {dst}")


def create_master_reduced():
    """Create Master_9500_reduced.dss.

    Based on Master-unbal-initial-config.dss (canonical source), with reductions:
    - Geometry-based line definitions (matches canonical source)
    - No secondary/triplex (LoadXfmrCodes, TriplexLineCodes, TriplexLines removed)
    - Primary MV loads only (Loads_primary.dss replaces UnbalancedLoads.dss)
    - No capacitors/capcontrols
    - No Generators.dss (LV DER step-up transformers removed, diesel/LNG/MT not modelled)
    - EnergyStorage_9500_noder.dss (ESS step-up transformer removed)
    - PVSystems_primary.dss (MV primary PV)
    """
    dst = DSS_DIR / "Master_9500_reduced.dss"

    content = """\
// Master file for 9500-Node IEEE Test Feeder — MV Primary Reduced Circuit
// Based on: Master-unbal-initial-config.dss (canonical unbalanced case)
// Reduction: no secondary loads/xfmrs, no LoadXfmrCodes, no TriplexLines,
//            no capacitors/capcontrols, no LV DER step-up transformers,
//            RegControls already commented out in Regulators.dss and Transformers.dss.

Clear

New Circuit.final9500node_reduced

! Make the source stiff with small impedance
~ pu=1.05  r1=0  x1=0.001  r0=0  x0=0.001

Redirect  WireData.dss
Redirect  CableData.dss
! LineCodes-based line definitions (all tie switches active)
! Note: LinesSwitchesGeometry.dss has most tie switches commented out;
!       LinesSwitchesLineCodes.dss is the complete topology file.
Redirect  LineCodes.dss
!Redirect  LineGeometry.dss
! Triplex excluded (secondary network removed)
!Redirect  TriplexLineCodes.dss

! MV primary lines only — DER 480V LV lines/switches removed
Redirect  LinesSwitches_9500_noder.dss
!Redirect  LinesSwitchesLineCodes.dss

Redirect  Transformers.dss
! Note: RegControls are already commented out in Transformers.dss and Regulators.dss
!       No Disable commands needed for 9500.

! Service transformer codes excluded (secondary network removed)
!Redirect  LoadXfmrCodes.dss
! Triplex lines excluded (secondary network removed)
!Redirect  TriplexLines.dss

! Primary MV loads only (aggregated at primary buses; UnbalancedLoads.dss excluded)
Redirect  Loads_primary.dss
!Redirect  UnbalancedLoads.dss

! No capacitors
!Redirect  Capacitors.dss
!Redirect  CapControls.dss

! Regulators as fixed-ratio transformers (RegControls already commented in source)
Redirect  Regulators.dss

! Exclude Generators.dss — diesel/LNG/MT not modelled; LV step-up transformers removed
!Redirect  Generators.dss

! MV batteries (Battery1/2 at 0.48kV already commented; ESS step-up transformer removed)
Redirect  EnergyStorage_9500_noder.dss

! Primary MV PV systems
Redirect  PVSystems_primary.dss

! MV-only voltage bases (0.48 kV base excluded — no LV sub-networks)
Set voltagebases=[115, 69, 12.47]
Calcvoltagebases

! Normal feeder open switches (same as Master-unbal-initial-config.dss)
open Line.WF856_48332_sw
open Line.WG127_48332_sw
open LINE.LN0653457_SW
open LINE.V7173_48332_SW
open LINE.TSW803273_SW
open LINE.A333_48332_SW
open LINE.TSW320328_SW
open LINE.A8645_48332_SW
open LINE.TSW568613_SW

Set Maxiterations=30 MaxControlIter=100
"""

    dst.write_text(content)
    print(f"[master] Created {dst}")


def parse_and_save():
    """Compile the reduced master, parse, and save CSVs."""
    sys.path.insert(0, str(ROOT))
    from dssconverter.dssparser import DSSParser

    master = DSS_DIR / "Master_9500_reduced.dss"
    print(f"\n[parse] Compiling {master.name} ...")
    dss_data = DSSParser(str(master))

    print("\n[parse] Circuit summary:")
    print(f"  Buses    : {len(dss_data.bus_data)}")
    print(f"  Branches : {len(dss_data.branch_data)}")
    print(f"  Gens (PV): {len(dss_data.gen_data)}")
    print(f"  Batteries: {len(dss_data.bat_data)}")
    print(f"  Caps     : {len(dss_data.cap_data)}")
    print(f"  Regs     : {len(dss_data.reg_data)}")

    # Verify no LV branches remain (v_ln_base is line-to-neutral base in V or kV)
    import re as _re
    _lv_pat = _re.compile(
        r"DER480|DER-\d|-WT\d|-DIES\d|-LNG\d|-MT\d|-ESS\d", _re.IGNORECASE
    )
    lv_branches = dss_data.branch_data[
        dss_data.branch_data["from_name"].str.contains(_lv_pat)
        | dss_data.branch_data["to_name"].str.contains(_lv_pat)
    ]
    if not lv_branches.empty:
        print(f"\n  WARNING: {len(lv_branches)} LV DER branches still present!")
        print(lv_branches[["fb", "tb", "from_name", "to_name"]].to_string())
    else:
        print("  LV check : OK — no LV DER branches present")

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    dss_data.branch_data.to_csv(CSV_DIR / "branch_data.csv", index=False)
    dss_data.bus_data.to_csv(CSV_DIR / "bus_data.csv", index=False)
    dss_data.cap_data.to_csv(CSV_DIR / "cap_data.csv", index=False)
    dss_data.gen_data.to_csv(CSV_DIR / "gen_data.csv", index=False)
    dss_data.reg_data.to_csv(CSV_DIR / "reg_data.csv", index=False)
    dss_data.bat_data.to_csv(CSV_DIR / "battery_data.csv", index=False)

    print(f"\n[parse] CSVs saved to {CSV_DIR}")


if __name__ == "__main__":
    print("=== IEEE 9500 Reduced Circuit Builder ===\n")
    create_lines_noder()
    create_energystorage_noder()
    create_master_reduced()
    parse_and_save()
    print("\n=== Done ===")
