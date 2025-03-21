import os
def create_branch_dss(data,script_name):
    # Get the current script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, script_name)

    P_base = 1e6
    V_base = 2400
    z_base = (V_base ** 2) / P_base

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

    # ---------------------------------------------------------
    # 4) Writing the script
    # ---------------------------------------------------------
    with open(file_path, 'w') as f:
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

            f.write(
                f"New Line.line_{fb}_{tb} phases={nphases} Bus1={fb}.{busconf} Bus2={tb}.{busconf} rmatrix=({rmatrix_str}) xmatrix=({xmatrix_str})\n")

    print(f"BranchDSS script saved as {file_path}")

def create_loads_dss(data,script_name):
    # Get the current script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, script_name)

    P_base = 1e6

    # A small helper for mapping phase letters to integer indices
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}

    # finding loads when loadshape multiplier is one

    t_one = next((t for t, m in data['loadshape'].items() if m == 1), None)

    # 4b) Add loads from p_L, q_L
    # -----------------------------------------------------
    with open(file_path, 'w') as f:
        for i in data['Nset']:
            for ph in data['phases']:
                # p_L is time dependent, q_L might be time dependent or not
                p_kw = data['p_L'][t_one,i,ph] * (P_base/1000) # real (kW)
                q_kvar = data['q_L'][t_one,i,ph] * (P_base/1000)# reactive (kVar) - if it’s not scaled by time, adapt as needed

                phase_int = phase_to_idx[ph]
                if p_kw != 0 or q_kvar != 0:
                    f.write(f"New Load.load_{i}_{ph} phases=1 "
                        f"Bus1={i}.{phase_int} conn=wye kv=2.4 "
                        f"kw={p_kw} kvar={q_kvar} Vminpu = 0.95 Vmaxpu = 1.05\n")

    print(f"LoadsDSS script saved as {file_path}")

def create_pv_dss(data,script_name):
    # Get the current script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, script_name)

    P_base = 1e6

    # A small helper for mapping phase letters to integer indices
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}

    # finding time when pvshape multiplier is one
    t_one = next((t for t, m in data['pvshape'].items() if m == 1), None)

    # -----------------------------------------------------
    # 4c) Add PV from p_D (data)
    # -----------------------------------------------------
    with open(file_path, 'w') as f:
        for i in data['Dset']:
            for ph in data['phases']:
                phase_int = phase_to_idx[ph]
                p_pv_kw = data['p_D'][t_one,i,ph] * (P_base/1000)
                s_max = data['s_D'][(i, ph)] * (P_base / 1000)  # max apparent power (kVA)

                f.write(f"New PVSystem.PV_{i}_{ph} phases=1 "
                        f"bus1={i}.{phase_int} kv=2.4 irradiance = 1 "
                        f"kva={s_max} Pmpp={p_pv_kw} "
                        f"Vmaxpu=1.05 Vminpu=0.95 %cutin=0.001 %cutout=0.001\n")

    print(f"pvDSS script saved as {file_path}")


def create_battery_dss(data, script_name):
    # Get the current script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, script_name)

    P_base = 1e6

    # A small helper for mapping phase letters to integer indices
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}

    # -----------------------------------------------------
    # 4c) Add PV from p_D (data)
    # -----------------------------------------------------
    with open(file_path, 'w') as f:
        # Add batteries from net power (Pnet_batt)
        # -----------------------------------------------------
        for i in data['Bset']:
            for ph in data['phases']:
                phase_int = phase_to_idx[ph]
                s_batt_rating = data['s_B'][(i, ph)] * (P_base / 1000)
                eff_charge = data['eta_c'][(i, ph)] * 100
                eff_discharge = data['eta_d'][(i, ph)] * 100
                kwhrated = data['p_B'][(i, ph)] * (P_base / 1000)
                kwrated = data['p_B'][(i, ph)] * (P_base / 1000)
                stored = 62.5
                reserved = 30

                f.write(
                    f"New Storage.Batt_{i}_{ph} phases=1 bus1={i}.{phase_int} "
                    f"kv=2.4 kva={s_batt_rating} kvar = 0 "
                    f"%EffCharge={eff_charge} %EffDischarge={eff_discharge} "
                    f"Vmaxpu=1.05 Vminpu=0.95 %IdlingKw=0 kwhrated={kwhrated} kwrated={kwrated} %stored={stored} %reserve={reserved} DispMode = External\n")

    print(f"batteryDSS script saved as {file_path}")

def create_master_dss(data,script_name):
    # Get the current script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, script_name)

    # Identify your substation bus—assuming the first in substationBus
    substation_bus = data['substationBus'][0]

    # ---------------------------------------------------------
    # 4) Writing the script
    # ---------------------------------------------------------
    with open(file_path, 'w') as f:
        # Clear and create new circuit
        f.write("clear\n")
        f.write("set defaultbasefrequency=60\n")
        f.write(f"New Circuit.myCircuit basekv=4.16 bus1={substation_bus}.1.2.3 pu=1.05 phases=3 MVAsc3=20000 MVASC1=21000 R1=0 X1=0.0001 R0=0 X0=0.0001\n")
        f.write(f"New Vsource.src basekv=4.16 bus1={substation_bus}.1.2.3 pu=1.05 phases=3\n")

        f.write(f"Redirect BranchData.dss\n")
        f.write(f"Redirect Loads.dss\n")
        f.write(f"Redirect PVSystem.dss\n")
        f.write(f"Redirect Storage.dss\n")

        f.write(f"Set voltageBases=[4.16]\n")
        f.write(f"Calcvoltagebases \n")
        f.write(f"Set mode = Daily\n")
        f.write(f"Set stepsize = 1h\n")
        f.write(f"Set number = 1\n")

    print(f"master_dss script saved as {file_path}")

def create_opendss_scripts(data):

    create_branch_dss(data,"BranchData.dss")
    create_loads_dss(data,"Loads.dss")
    create_pv_dss(data,"PVSystem.dss")
    create_battery_dss(data,"Storage.dss")
    create_master_dss(data, "Master.dss")



    print("All opendss scripts saved")
