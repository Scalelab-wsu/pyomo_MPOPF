"""Quick diagnostic for IEEE_9500 PV / load / branch / bus / battery consistency.

Compares three sources:
  (A) CSV data parsed by parse_all_data_phase_aware  -> 'parsed'
  (B) Linear-OPF optimizer output                    -> 'opt'
  (C) OpenDSS run after Edit PVSystem/Storage        -> 'dss'

For each time step prints total PV kW, PV kvar, load kW, load kvar,
battery net kW. Also prints element counts and inverter rating mismatches.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import opendssdirect as dss

from Parser.parse_phase_aware import parse_all_data_phase_aware
from Build_Model.Objective import cost_minimize_with_scd
from Centralized.copf import solve_copf
from OpenDss.OpenDssValidate import (
    set_pv_controls, set_battery_controls,
    get_load_powers_opendss_powerflow,
    get_pv_powers_opendss_powerflow,
    get_total_battery_power_opendss,
    get_total_nameplate_load_powers,
    get_total_nameplate_pv_powers,
)

wd = os.path.dirname(os.path.abspath(__file__))
system_name = 'IEEE_9500'
filepath = os.path.join(wd, "rawData", system_name, "csvs")
dss_path = os.path.join(wd, "rawData", system_name, "dss_scripts", "Master.dss")

bus_data = pd.read_csv(os.path.join(filepath, "bus_data.csv"))
branch_data = pd.read_csv(os.path.join(filepath, "branch_data.csv"))
gen_data = pd.read_csv(os.path.join(filepath, "gen_data.csv"))
bat_data = pd.read_csv(os.path.join(filepath, "battery_data.csv"))
loadshape_data = pd.read_csv(os.path.join(filepath, "default_loadshape.csv"))
pvshape_data = pd.read_csv(os.path.join(filepath, "pv_loadshape.csv"))
price = 0.15 * loadshape_data['M'] + 0.15

start_step = 1
n_steps = 24  # full day
P_base = 1e6

data = parse_all_data_phase_aware(
    bus_data, branch_data, gen_data, bat_data,
    loadshape=loadshape_data, pvshape=pvshape_data, price=price,
    start_step=start_step, n_steps=n_steps,
)

print("=" * 70)
print("ELEMENT COUNTS")
print("=" * 70)
print(f"  buses  (parsed Nset)       : {len(data['Nset'])}")
print(f"  branches (parsed Lset)     : {len(data['Lset'])}")
print(f"  PVs / gens (parsed Dset)   : {len(data['Dset'])}")
print(f"  batteries (parsed Bset)    : {len(data['Bset'])}")

# ---------- (A) parsed totals ----------
parsed_pv_kw_t = {t: 0.0 for t in data['Tset']}
for (t, j, ph), v in data['p_D'].items():
    parsed_pv_kw_t[t] += v * P_base / 1e3
parsed_load_kw_t = {t: 0.0 for t in data['Tset']}
parsed_load_kvar_t = {t: 0.0 for t in data['Tset']}
for (t, i, ph), v in data['p_L'].items():
    parsed_load_kw_t[t] += v * P_base / 1e3
for (t, i, ph), v in data['q_L'].items():
    parsed_load_kvar_t[t] += v * P_base / 1e3

# Inverter ratings sanity
parsed_pv_kva_total = sum(data['s_D'].values()) * P_base / 1e3
parsed_bat_pmax_total = sum(data['p_B'].values()) * P_base / 1e3
parsed_bat_emax_total = sum(data['s_B'].values()) * P_base / 1e3  # hmax: kWh
print(f"  total PV nameplate kVA     : {parsed_pv_kva_total:.2f}")
print(f"  total bat P_max kW         : {parsed_bat_pmax_total:.2f}")
print(f"  total bat E_max kWh        : {parsed_bat_emax_total:.2f}")

# ---------- (B) optimizer ----------
print("\nSolving linear OPF...")
copfVals = solve_copf(data, cost_minimize_with_scd, solver='highs',
                      alpha_scd=1e-1, non_linear=False, isocp=False,
                      p_control=False, integer=False,
                      single_battery_variable=False)

opt_pv_kw_t = {t: 0.0 for t in data['Tset']}
opt_pv_kvar_t = {t: 0.0 for t in data['Tset']}
for (t, j, ph), v in copfVals.get('p_D', {}).items():
    opt_pv_kw_t[t] += v * P_base / 1e3
for (t, j, ph), v in copfVals.get('q_D', {}).items():
    opt_pv_kvar_t[t] += v * P_base / 1e3

# ---------- (C) OpenDSS ----------
print("\nRunning OpenDSS (Daily mode, with Edit PV / Storage)...")
dss.Text.Command("clear")
dss.Text.Command(f'Redirect "{dss_path}"')

# Same default loadshape used in main / validation
load_profile = [
    0.677, 0.6256, 0.6087, 0.5833, 0.58028, 0.6025, 0.657, 0.7477,
    0.832, 0.88, 0.94, 0.989, 0.985, 0.98, 0.9898, 0.999,
    1, 0.958, 0.936, 0.913, 0.876, 0.876, 0.828, 0.756,
]
dss.Text.Command(
    'New Loadshape.loadshape npts=24 interval=1 mult=('
    + ' '.join(map(str, load_profile)) + ')'
)
dss.Text.Command('BatchEdit Load..* Daily=loadshape')
dss.Text.Command('Set mode = Daily')
dss.Text.Command('Set stepsize = 1h')
dss.Text.Command('Set number = 1')
dss.Text.Command(f'Set hour = {start_step - 1}')

# Counts from DSS
n_dss_buses = dss.Circuit.NumBuses()
n_dss_loads = dss.Loads.Count()
n_dss_pv = dss.PVsystems.Count()
n_dss_bat = dss.Storages.Count()
n_dss_lines = dss.Lines.Count()
n_dss_xfmr = dss.Transformers.Count()
print(f"  DSS buses                  : {n_dss_buses}")
print(f"  DSS loads                  : {n_dss_loads}")
print(f"  DSS PVsystems              : {n_dss_pv}")
print(f"  DSS Storages               : {n_dss_bat}")
print(f"  DSS lines                  : {n_dss_lines}")
print(f"  DSS transformers           : {n_dss_xfmr}")

dss_pv_nameplate_kw = get_total_nameplate_pv_powers()
dss_load_nameplate_kw, dss_load_nameplate_kvar = get_total_nameplate_load_powers()
print(f"  DSS PV nameplate Pmpp tot  : {dss_pv_nameplate_kw:.2f} kW")
print(f"  DSS load nameplate         : {dss_load_nameplate_kw:.2f} kW, {dss_load_nameplate_kvar:.2f} kvar")
print(f"  parsed load at loadshape=1 : {sum(bus_data['pl_a'])+sum(bus_data['pl_b'])+sum(bus_data['pl_c']):.4f} pu = {(sum(bus_data['pl_a'])+sum(bus_data['pl_b'])+sum(bus_data['pl_c']))*P_base/1e3:.2f} kW")

# Per-timestep DSS comparison
print("\n" + "=" * 90)
print(f"{'t':>3} | {'parsedPV_kW':>12} {'optPV_kW':>10} {'dssPV_kW':>10} | {'optPV_kvar':>11} {'dssPV_kvar':>11} | {'parsedLoad_kW':>13} {'dssLoad_kW':>12} | {'optBat_kW':>10} {'dssBat_kW':>10}")
print("=" * 90)

for t in data['Tset']:
    set_pv_controls(data, copfVals, t, P_base)
    set_battery_controls(data, copfVals, t, P_base)
    dss.Text.Command('solve')

    pv_powers = get_pv_powers_opendss_powerflow()
    load_powers = get_load_powers_opendss_powerflow()
    bat_powers = get_total_battery_power_opendss()
    opt_bat_kw = sum(
        copfVals['P_d'].get((t, j), 0) - copfVals['P_c'].get((t, j), 0)
        for j in data['Bset']
    ) * P_base / 1e3
    print(
        f"{t:>3} | "
        f"{parsed_pv_kw_t[t]:>12.2f} {opt_pv_kw_t[t]:>10.2f} {pv_powers['total_pv_t_kW']:>10.2f} | "
        f"{opt_pv_kvar_t[t]:>11.2f} {pv_powers['total_pv_t_kVAr']:>11.2f} | "
        f"{parsed_load_kw_t[t]:>13.2f} {load_powers['total_load_t_kW']:>12.2f} | "
        f"{opt_bat_kw:>10.2f} {bat_powers['battery_real_power_t_kW']:>10.2f}"
    )

# kVA mismatch check between DSS and CSV for individual PVs
print("\nDSS vs CSV PV kVA-rating discrepancies (top 10 by |delta|):")
deltas = []
gen_lookup = gen_data.set_index('name')
pv_flag = dss.PVsystems.First()
while pv_flag:
    name = dss.PVsystems.Name()
    bus = dss.CktElement.BusNames()[0].split('.')[0]
    dss.Circuit.SetActiveElement(f"PVSystem.{name}")
    kva_dss = dss.PVsystems.kVARated()
    if bus in gen_lookup.index:
        row = gen_lookup.loc[bus]
        # s_max columns are per-phase pu; the parser sums per phase later
        s_max_pu = sum(row.get(f's{ph}_max', 0) for ph in 'abc')
        kva_csv = s_max_pu * P_base / 1e3
        delta = kva_dss - kva_csv
        deltas.append((abs(delta), name, bus, kva_dss, kva_csv, delta))
    pv_flag = dss.PVsystems.Next()
deltas.sort(reverse=True)
for absd, name, bus, kva_dss, kva_csv, d in deltas[:10]:
    print(f"  PV {name:<12} bus={bus:<14} DSS_kVA={kva_dss:>7.2f}  CSV_kVA={kva_csv:>7.2f}  delta={d:>7.2f}")
print(f"  ({len(deltas)} PVs compared)")
