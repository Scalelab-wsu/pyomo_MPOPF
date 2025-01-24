
import opendssdirect as dss
import os

def edit_loads(data,t,P_base):
    load_id = dss.Loads.First()
    while load_id > 0:
        load_name = dss.Loads.Name()
        # Split the string by underscores
        parts = load_name.split('_')

        # Extract the desired values
        i = int(parts[1])  # '3'
        ph = parts[2]  # 'a'

        p_kw = data['p_L'][(t, i, ph)] * (P_base / 1000)
        q_kvar = data['q_L'][(t, i, ph)] * (P_base / 1000)

        ## setting P and Q for Loads
        dss.Text.Command(f"Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
        print(f"Time Step {t}: Setting load {load_name} with kw: {p_kw} and kvar: {q_kvar}")

        load_id = dss.Loads.Next()


def set_pv_controls(data, modelVals,t, P_base):
    pv_id = dss.PVsystems.First()
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        # Split the string by underscores
        parts = pv_name.split('_')

        # Extract the desired values
        i = int(parts[1])  # '3'
        ph = parts[2]  # 'a'

        p_pv = data['p_D'][(t, i, ph)] * (P_base / 1000)  # kW
        q_pv = modelVals['q_D'][(t, i, ph)] * (P_base / 1000)  # kVar

        dss.Text.Command(f"Edit PVSystem.{pv_name} Pmpp={p_pv} kvar={q_pv}")
        print(f"Time Step {t}: Setting PV {pv_name} with kw: {p_pv} and kvar : {q_pv}")

        pv_id = dss.PVsystems.Next()

def set_battery_controls(data, modelVals,t, P_base):
    storage_id = dss.Storages.First()
    while storage_id > 0:
        storage_name = dss.Storages.Name()
        parts = storage_name.split('_')
        i = int(parts[1])
        ph = parts[2]
        p_dis = modelVals['P_d'][(t, i, ph)] * (P_base / 1000)
        p_chg = modelVals['P_c'][(t, i, ph)] * (P_base / 1000)
        Pnet_batt = (p_dis - p_chg)
        dss.Text.Command(f"Edit Storage.{storage_name} kw={Pnet_batt}")
        print(f"Time Step {t}: Setting Battery {storage_name} with kw: {Pnet_batt}")

        storage_id = dss.Storages.Next()

def run_opendss_validation(data, modelVals):
    # Save the OpenDSS script in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, "..","rawData","IEEE_123_other","dss_scripts","Master.dss")

    # ---------------------------------------------------------
    # 1) Initialize a results dictionary in the same format as modelVals
    # ---------------------------------------------------------

    P_base = 1e6
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

    ## Now doing the time series loop
    dss.Text.Command("clear")
    # Redirect OpenDSS to use the generated script
    dss.Text.Command(f"Redirect \"{script_path}\"")

    for t in data['Tset']:
        edit_loads(data,t,P_base)
        set_pv_controls(data,modelVals,t, P_base)
        set_battery_controls(data,modelVals,t, P_base)
        dss.Text.Command("solve")

        dss.Circuit.SetActiveElement("Vsource.src")
        vs_powers = dss.CktElement.Powers()
        for idx, ph in enumerate(['a', 'b', 'c']):
            p_phase = -vs_powers[2 * idx]  * (1000/P_base) # Negate to represent injection
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

                # Get the bus names and parse them
                bus_names = dss.CktElement.BusNames()  # e.g., ['bus1.1.2.3', 'bus2.1.2.3']
                if len(bus_names) > 0:
                    # Parse the phases from the bus configuration (e.g., 'bus1.1.2.3')
                    busconf = bus_names[0].split('.')[1:]  # ['1', '2', '3'] if 3 phases
                else:
                    busconf = []
                # busconf = "1.2.3" or "1.2" or "2.3", etc.
                # Let's parse that:
                if ph_idx < len(busconf):
                    ph_num = busconf[ph_idx]  # e.g. '1' => a, '2' => b, '3' => c
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
                    openDssVals['q_D'][(t, j, ph)] = pv_powers[1]*(1000/P_base)
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
                p_batt = powers[0]*(1000/P_base)

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

