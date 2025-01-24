import opendssdirect as dss
import pandas as pd
import numpy as np



def run_opendss_validation(data, modelVals):
    # ---------------------------------------------------------
    # 1) Initialize a results dictionary in the same format as modelVals
    # ---------------------------------------------------------

    P_base = 1e6
    V_base = 2400
    z_base = (V_base ** 2)/P_base
    openDssVals = {
        'P_subs': {},  # (t, ph)
        'P': {},  # (t, (fb, tb), ph)
        'Q': {},  # (t, (fb, tb), ph)
        'v': {},  # (t, j, ph)
        'q_D': {},  # (t, j, ph)
        'P_c': {},  # (t, j, ph)
        'P_d': {},  # (t, j, ph)
        'B': {},  # (t, j, ph)
    }

    # A small helper for mapping phase letters to integer indices
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}

    # ---------------------------------------------------------
    # 2) Precompute net battery power = P_d - P_c from modelVals

    Pnet_batt = {}
    for t in data['Tset']:
        for j in data['Bset']:
            for ph in data['phases']:
                p_dis = modelVals['P_d'][(t, j, ph)] * P_base/1000
                p_chg = modelVals['P_c'][(t, j, ph)] * P_base/1000
                Pnet_batt[(t, j, ph)] = (p_dis - p_chg)

    # ---------------------------------------------------------
    # 3) Prepare line parameters from R/X matrices

    line_params = {}
    for (fb, tb) in data['Lset']:
        # Retrieve each element from the sparse matrices
        raa = data['r']['aa'][fb, tb] * z_base
        rab = data['r']['ab'][fb, tb] * z_base
        rbb = data['r']['bb'][fb, tb] * z_base
        rac = data['r']['ac'][fb, tb] * z_base
        rbc = data['r']['bc'][fb, tb] * z_base
        rcc = data['r']['cc'][fb, tb] * z_base

        xaa = data['x']['aa'][fb, tb] * z_base
        xab = data['x']['ab'][fb, tb] * z_base
        xbb = data['x']['bb'][fb, tb] * z_base
        xac = data['x']['ac'][fb, tb] * z_base
        xbc = data['x']['bc'][fb, tb] * z_base
        xcc = data['x']['cc'][fb, tb] * z_base

        # Decide which phases are present
        has_a = (abs(raa) > 1e-12 or abs(xaa) > 1e-12)
        has_b = (abs(rbb) > 1e-12 or abs(xbb) > 1e-12)
        has_c = (abs(rcc) > 1e-12 or abs(xcc) > 1e-12)

        # Build strings the same way you did in your CSV-based code
        if has_a and has_b and has_c:
            nphases = 3
            busconf = "1.2.3"
            rmatrix_str = f"{raa} | {rab} {rbb} | {rac} {rbc} {rcc}"
            xmatrix_str = f"{xaa} | {xab} {xbb} | {xac} {xbc} {xcc}"
        elif has_a and has_b:
            nphases = 2
            busconf = "1.2"
            rmatrix_str = f"{raa} | {rab} {rbb}"
            xmatrix_str = f"{xaa} | {xab} {xbb}"
        elif has_a and has_c:
            nphases = 2
            busconf = "1.3"
            rmatrix_str = f"{raa} | {rac} {rcc}"
            xmatrix_str = f"{xaa} | {xac} {xcc}"
        elif has_b and has_c:
            nphases = 2
            busconf = "2.3"
            rmatrix_str = f"{rbb} | {rbc} {rcc}"
            xmatrix_str = f"{xbb} | {xbc} {xcc}"
        elif has_a:
            nphases = 1
            busconf = "1"
            rmatrix_str = f"{raa}"
            xmatrix_str = f"{xaa}"
        elif has_b:
            nphases = 1
            busconf = "2"
            rmatrix_str = f"{rbb}"
            xmatrix_str = f"{xbb}"
        elif has_c:
            nphases = 1
            busconf = "3"
            rmatrix_str = f"{rcc}"
            xmatrix_str = f"{xcc}"
        else:
            # No phases? This would be strange, skip it
            continue

        line_params[(fb, tb)] = {
            'nphases': nphases,
            'busconf': busconf,
            'rmatrix': rmatrix_str,
            'xmatrix': xmatrix_str
        }

    # Identify your substation bus—assuming the first in substationBus
    substation_bus = data['substationBus'][0]

    # ---------------------------------------------------------
    # 4) Main time loop
    # ---------------------------------------------------------
    for t in data['Tset']:
        # Clear and create new circuit
        dss.Text.Command("clear")
        dss.Text.Command("set defaultbasefrequency=60")
        dss.Text.Command("New Circuit.myCircuit "
                         f"basekv=4.16 bus1={substation_bus}.1.2.3 pu=1.05 phases=3 "
                         "MVAsc3=20000 MVASC1=21000 R1=0 X1=0.0001 R0=0 X0=0.0001")
        dss.Text.Command(f"New Vsource.Src phases=3 bus1={substation_bus}.1.2.3 basekv=4.16 pu=1.05")

        # -----------------------------------------------------
        # 4a) Add lines
        # -----------------------------------------------------
        for (fb, tb) in data['Lset']:
            # Skip if not in line_params (i.e. if no valid phases)
            if (fb, tb) not in line_params:
                continue
            lp = line_params[(fb, tb)]
            nphases = lp['nphases']
            busconf = lp['busconf']
            rmatrix_str = lp['rmatrix']
            xmatrix_str = lp['xmatrix']

            dss.Text.Command(
                f"New Line.line_{fb}_{tb} phases={nphases} "
                f"Bus1={fb}.{busconf} Bus2={tb}.{busconf} "
                f"rmatrix=({rmatrix_str}) xmatrix=({xmatrix_str})"
            )
            print(f"New Line.line_{fb}_{tb} phases={nphases} Bus1={fb}.{busconf} Bus2={tb}.{busconf} rmatrix=({rmatrix_str}) xmatrix=({xmatrix_str}")
        # -----------------------------------------------------
        # 4b) Add loads from p_L, q_L
        # -----------------------------------------------------
        for i in data['Nset']:
            for ph in data['phases']:
                # p_L is time dependent, q_L might be time dependent or not
                p_kw = data['p_L'][(t, i, ph)] * P_base/1000 # real (kW)
                q_kvar = data['q_L'][(t,i, ph)] * P_base/1000   # reactive (kVar) - if it’s not scaled by time, adapt as needed

                if abs(p_kw) > 1e-9 or abs(q_kvar) > 1e-9:
                    phase_int = phase_to_idx[ph]
                    dss.Text.Command(
                        f"New Load.load_{i}_{ph} phases=1 "
                        f"Bus1={i}.{phase_int} conn=wye kv=2.4 "
                        f"kw={p_kw} kvar={q_kvar}"
                    )
                    print(f"New Load.load_{i}_{ph} phases=1 "
                        f"Bus1={i}.{phase_int} conn=wye kv=2.4 "
                        f"kw={p_kw} kvar={q_kvar}")
        # -----------------------------------------------------
        # 4c) Add PV from p_D (data) and q_D (modelVals)
        # -----------------------------------------------------
        for i in data['Dset']:
            for ph in data['phases']:
                phase_int = phase_to_idx[ph]
                p_pv_kw = data['p_D'][(t, i, ph)] * P_base/1000
                q_pv_kvar = modelVals['q_D'][(t, i, ph)] * P_base/1000   # from the solution
                s_max = data['s_D'][(i, ph)] * P_base/1000 # max apparent power (kVA)

                if abs(p_pv_kw) > 1e-9 or abs(q_pv_kvar) > 1e-9:
                    dss.Text.Command(
                        f"New PVSystem.PV_{i}_{ph} phases=1 "
                        f"bus1={i}.{phase_int} kv=2.4 irradiance = 1 "
                        f"kva={s_max} Pmpp={p_pv_kw} kvar={q_pv_kvar} "
                        f"Vmaxpu=1.05 Vminpu=0.95 %cutin=0.001 %cutout=0.001"
                    )
                    print(f"New PVSystem.PV_{i}_{ph} phases=1 "
                        f"bus1={i}.{phase_int} kv=2.4 irradiance = 1 "
                        f"kva={s_max} Pmpp={p_pv_kw} kvar={q_pv_kvar} "
                        f"Vmaxpu=1.05 Vminpu=0.95 %cutin=0.001 %cutout=0.001")

        # -----------------------------------------------------
        # 4d) Add batteries from net power (Pnet_batt)
        # -----------------------------------------------------
        for i in data['Bset']:
            for ph in data['phases']:
                phase_int = phase_to_idx[ph]
                p_net = Pnet_batt[(t, i, ph)]
                s_batt_rating = data['s_B'][(i, ph)] * P_base/1000
                eff_charge = data['eta_c'][(i, ph)] * 100
                eff_discharge = data['eta_d'][(i, ph)] * 100
                kwhrated = data['p_B'][(i,ph)] * P_base/1000
                kwrated = data['p_B'][(i,ph)] * P_base/1000
                stored = 60
                reserved = 30


                # If you have battery kWh capacity, you can set it using 'kwhrated=...'
                # For demonstration, we use p_batt_rating as kW rated
                # The user can adapt if they have bmax, bmin, etc.
                dss.Text.Command(
                    f"New Storage.Batt_{i}_{ph} phases=1 bus1={i}.{phase_int} "
                    f"kv=2.4 kva={s_batt_rating} kvar = 0 kw={p_net} "
                    f"%EffCharge={eff_charge} %EffDischarge={eff_discharge} "
                    f"Vmaxpu=1.05 Vminpu=0.95 %IdlingKw=0 kwhrated={kwhrated} kwrated={kwrated} %stored={stored} %reserve={reserved} DispMode = External"
                )
                print(f"New Storage.Batt_{i}_{ph} phases=1 bus1={i}.{phase_int} "
                    f"kv=2.4 kva={s_batt_rating} kvar = 0 kw={p_net} "
                    f"%EffCharge={eff_charge} %EffDischarge={eff_discharge} "
                    f"Vmaxpu=1.05 Vminpu=0.95 %IdlingKw=0")

        # -----------------------------------------------------
        # 4e) Solve and collect results
        # -----------------------------------------------------
        dss.Text.Command("Set voltagebases=[4.16]")
        dss.Text.Command("calcv")
        dss.Text.Command("Set mode = Daily")
        dss.Text.Command("Set stepsize = 1h")
        dss.Text.Command("Set number = 1")
        dss.Text.Command("solve")


        # ~~~~~~~~~~~~~~
        # Substation power by phase => openDssVals['P_subs'][(t, ph)]
        # ~~~~~~~~~~~~~~
        dss.Circuit.SetActiveElement("Vsource.src")
        vs_powers = dss.CktElement.Powers()
        for idx, ph in enumerate(['a', 'b', 'c']):
            p_phase = -vs_powers[2 * idx]  # Negate to represent injection
            openDssVals['P_subs'][(t, ph)] = p_phase

        # ~~~~~~~~~~~~~~
        # Collect line flows: P, Q => openDssVals['P'] and openDssVals['Q']
        # ~~~~~~~~~~~~~~
        for (fb, tb) in data['Lset']:
            # We named lines as "Line.line_{fb}_{tb}"
            line_name = f"Line.line_{fb}_{tb}"
            if line_name.lower() not in [elm.lower() for elm in dss.Circuit.AllElementNames()]:
                continue  # might not exist if zero phases

            dss.Circuit.SetActiveElement(line_name)
            powers = dss.CktElement.Powers()  # [P1, Q1, P2, Q2, ...]
            num_ph = dss.CktElement.NumPhases()  # how many phases this line actually has

            # We store the "sending-end" flows in openDssVals['P'][(t, (fb, tb), ph)] etc.
            # By default, first 2*num_ph entries are the sending-end, the next 2*num_ph are receiving-end.
            for ph_idx in range(num_ph):
                # Real power
                p_line = powers[2 * ph_idx]*1000/P_base
                q_line = powers[2 * ph_idx + 1]*1000/P_base

                # Identify which actual phases are used. This can be tricky if the line is 2-phase or 1-phase.
                # We'll assume the phases are in ascending order (1->2->3).
                # If you need a perfect match to your original (fb, tb, ph), you must do more advanced checking.
                # For demonstration, we guess if nphases=3 => phase = [a,b,c][ph_idx]
                # If nphases=2 => we check which 2 phases are present in busconf, etc.
                # We'll do a simpler approach: if line_params says "1.2.3", then ph=(a,b,c) in order

                nphases = line_params.get((fb, tb), {}).get('nphases', 0)
                busconf = line_params.get((fb, tb), {}).get('busconf', '')
                # busconf = "1.2.3" or "1.2" or "2.3", etc.
                # Let's parse that:
                busconf_parts = busconf.split('.')
                if ph_idx < len(busconf_parts):
                    ph_num = busconf_parts[ph_idx]  # e.g. '1' => a, '2' => b, '3' => c
                    ph_letter = {'1': 'a', '2': 'b', '3': 'c'}.get(ph_num, 'a')
                else:
                    ph_letter = 'a'  # fallback

                openDssVals['P'][(t, (fb, tb), ph_letter)] = p_line
                openDssVals['Q'][(t, (fb, tb), ph_letter)] = q_line

        # ~~~~~~~~~~~~~~
        # Collect bus voltages: v => openDssVals['v'][(t, j, ph)]
        # ~~~~~~~~~~~~~~
        # We can do that by retrieving the node voltage mag in p.u. for each bus, phase
        for ph in data['phases']:
            ph_num = phase_to_idx[ph]
            node_names = dss.Circuit.AllNodeNamesByPhase(ph_num)
            vmag_pu = dss.Circuit.AllNodeVmagPUByPhase(ph_num)

            for i_node, node_name in enumerate(node_names):
                # node_name might be "7.1" => bus=7, phase=1
                # bus_id is node_name.split('.')[0]
                bus_id = node_name.split('.')[0]
                # store
                openDssVals['v'][(t, int(bus_id), ph)] = vmag_pu[i_node]

        # ~~~~~~~~~~~~~~
        # Collect PV reactive powers: q_D => openDssVals['q_D'][(t, j, ph)]
        # We'll parse each PVSystem.PV_{j}_{ph} element
        # ~~~~~~~~~~~~~~
        for j in data['Dset']:
            for ph in data['phases']:
                pv_name = f"PVSystem.PV_{j}_{ph}"
                # Check existence
                if pv_name.lower() not in [elm.lower() for elm in dss.Circuit.AllElementNames()]:
                    # Might be zero power => skip
                    openDssVals['q_D'][(t, j, ph)] = 0.0
                    continue

                dss.Circuit.SetActiveElement(pv_name)
                pv_powers = dss.CktElement.Powers()  # [P1, Q1, P2, Q2, ...], typically 1-phase => first pair
                if len(pv_powers) >= 2:
                    # Real power = pv_powers[0], Reactive = pv_powers[1]
                    # We'll store Q
                    openDssVals['q_D'][(t, j, ph)] = pv_powers[1]*1000/P_base
                else:
                    openDssVals['q_D'][(t, j, ph)] = 0.0

        # ~~~~~~~~~~~~~~
        # Collect battery powers: P_c, P_d, B => openDssVals
        # We'll parse each Storage.Batt_{j}_{ph}
        # ~~~~~~~~~~~~~~
        for j in data['Bset']:
            for ph in data['phases']:
                batt_name = f"Storage.Batt_{j}_{ph}"
                if batt_name.lower() not in [elm.lower() for elm in dss.Circuit.AllElementNames()]:
                    openDssVals['P_c'][(t, j, ph)] = 0.0
                    openDssVals['P_d'][(t, j, ph)] = 0.0
                    openDssVals['B'][(t, j, ph)] = 0.0
                    continue

                dss.Circuit.SetActiveElement(batt_name)
                powers = dss.CktElement.Powers()  # [P1, Q1, P2, Q2, ...], typically 1-phase => first pair
                # P in kW: powers[0]. If +ve => battery injecting => discharging, if -ve => charging
                p_batt = powers[0]*1000/P_base

                # Split it:
                if p_batt >= 0:
                    # Discharging
                    openDssVals['P_d'][(t, j, ph)] = p_batt
                    openDssVals['P_c'][(t, j, ph)] = 0.0
                else:
                    # Charging
                    openDssVals['P_d'][(t, j, ph)] = 0.0
                    openDssVals['P_c'][(t, j, ph)] = -p_batt  # make it positive

                # B => we can read from dss.Storages.puSOC() or dss.Storages.StateOfCharge() if available
                soc_value = dss.Storages.puSOC()
                # store as fraction (0-1) or as %? ModelVals stored B in absolute (kWh) or fraction?
                # We'll store as fraction:
                openDssVals['B'][(t, j, ph)] = soc_value

    # ---------------------------------------------------------
    # 5) Return the results dictionary
    # ---------------------------------------------------------
    return openDssVals

