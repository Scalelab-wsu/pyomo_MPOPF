import numpy as np
import opendssdirect as dss
import os
import math
def collect_opendss_substationpower(openDssVals,t,P_base):
    ## for some reason this is not working
    dss.Circuit.SetActiveElement("Vsource.source")  # Use actual Vsource name
    vs_powers = dss.CktElement.Powers()
    for idx in range(dss.CktElement.NumPhases()):
        ph = ['a', 'b', 'c'][idx]
        p = -vs_powers[2 * idx] * 1000 / P_base
        q = -vs_powers[2 * idx + 1] * 1000 / P_base
        openDssVals['P_subs'][t, ph] = p
        openDssVals['Q_subs'][t, ph] = q

    return openDssVals

def collect_opendss_lineflows(openDssVals, t, data,P_base):
    flag = dss.PDElements.First()
    while flag:
        element_type = dss.CktElement.Name().lower().split(".")[0]

        if element_type not in ["line", "transformer", "reactor"]:
            flag = dss.PDElements.Next()
            continue

        if element_type == "line" and dss.Lines.IsSwitch():
            if dss.CktElement.IsOpen(1, 0) or dss.CktElement.IsOpen(2, 0):
                flag = dss.PDElements.Next()
                continue

        busnames    = dss.CktElement.BusNames()
        node_order  = dss.CktElement.NodeOrder()
        nodes       = [x for x in dict.fromkeys(node_order) if x != 0]
        n_phases    = dss.CktElement.NumPhases()
        line_powers = dss.CktElement.Powers()
        term1_nodes = nodes[:n_phases]

        fb_dss = busnames[0].split('.')[0]
        tb_dss = busnames[1].split('.')[0]

        if (fb_dss, tb_dss) in data['Lset']:
            fb, tb, flipped = fb_dss, tb_dss, False
        elif (tb_dss, fb_dss) in data['Lset']:
            fb, tb, flipped = tb_dss, fb_dss, True
        else:
            flag = dss.PDElements.Next()
            continue

        for index, node in enumerate(term1_nodes):
            ph = {1: 'a', 2: 'b', 3: 'c'}.get(node)
            if ph is None:
                continue
            p = line_powers[2 * index]     * 1000 / P_base
            q = line_powers[2 * index + 1] * 1000 / P_base
            if flipped:
                p, q = -p, -q
            openDssVals['P'][t, fb, tb, ph] = p
            openDssVals['Q'][t, fb, tb, ph] = q

        flag = dss.PDElements.Next()
    return openDssVals

def collect_opendss_voltages(openDssVals,t): # Activate all buses
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}
    phases = ['a', 'b', 'c']
    for ph in phases:
        ph_num = phase_to_idx[ph]
        node_names = dss.Circuit.AllNodeNamesByPhase(ph_num)
        vmag_pu = dss.Circuit.AllNodeVmagPUByPhase(ph_num)

        for i_node, node_name in enumerate(node_names):
            bus_id = node_name.split('.')[0]
            openDssVals['v'][t, bus_id, ph] = vmag_pu[i_node]
    return openDssVals


def collect_opendss_linecurrents(openDssVals, t, data):
    flag = dss.PDElements.First()
    while flag:
        element_type = dss.CktElement.Name().lower().split(".")[0]

        if element_type not in ["line", "transformer", "reactor"]:
            flag = dss.PDElements.Next()
            continue

        if element_type == "line" and dss.Lines.IsSwitch():
            if dss.CktElement.IsOpen(1, 0) or dss.CktElement.IsOpen(2, 0):
                flag = dss.PDElements.Next()
                continue

        busnames    = dss.CktElement.BusNames()
        node_order  = dss.CktElement.NodeOrder()
        nodes       = [x for x in dict.fromkeys(node_order) if x != 0]
        n_phases    = dss.CktElement.NumPhases()
        currents    = dss.CktElement.CurrentsMagAng()
        term1_nodes = nodes[:n_phases]

        fb_dss = busnames[0].split('.')[0]
        tb_dss = busnames[1].split('.')[0]

        if (fb_dss, tb_dss) in data['Lset']:
            fb, tb, flipped = fb_dss, tb_dss, False
        elif (tb_dss, fb_dss) in data['Lset']:
            fb, tb, flipped = tb_dss, fb_dss, True
        else:
            flag = dss.PDElements.Next()
            continue

        for index, node in enumerate(term1_nodes):
            ph = {1: 'a', 2: 'b', 3: 'c'}.get(node)
            if ph is None:
                continue
            I_mag = currents[2 * index]
            I_ang = currents[2 * index + 1]
            if flipped:
                I_ang = (I_ang + 180)
            openDssVals['I_mag'][t, fb, tb, ph] = I_mag
            openDssVals['I_ang'][t, fb, tb, ph] = I_ang * (math.pi / 180)

        flag = dss.PDElements.Next()
    return openDssVals

def collect_opendss_pvPowers(openDssVals,t, P_base):
    pv_id = dss.PVsystems.First()
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        dss.Circuit.SetActiveElement(f"PVsystem.{pv_name}")
        bus = dss.CktElement.BusNames()[0].split('.')[0]  # e.g., ["bus123", "1", "2"]
        node_order = dss.CktElement.NodeOrder()
        nodes = [x for x in dict.fromkeys(node_order) if x != 0]# e.g., ["1", "2"] for phases a, b
        for index, node in enumerate(nodes):
            ph = {1: 'a', 2: 'b', 3: 'c'}[node]
            p = -dss.CktElement.Powers()[2*index]* 1000 / P_base
            q = -dss.CktElement.Powers()[2*index+1]* 1000 / P_base
            openDssVals['p_D'][t, bus, ph] = p
            openDssVals['q_D'][t, bus, ph] = q
        pv_id = dss.PVsystems.Next()
    return openDssVals

def collect_opendss_batteryresults(data,openDssVals,t, P_base):
    bat_id = dss.Storages.First()
    while bat_id > 0:
        batt_name = dss.Storages.Name()
        dss.Circuit.SetActiveElement(f"Storage.{batt_name}")
        bus = dss.CktElement.BusNames()[0].split('.')[0]   # e.g., ["bus45", "3"]
        node_order = dss.CktElement.NodeOrder()
        nodes = [x for x in dict.fromkeys(node_order) if x != 0]
        p = -sum(dss.CktElement.Powers()[::2])* 1000 / P_base
        soc = dss.Storages.puSOC()#*data['b_R'][bus,ph] ## multiplying by rated to match optimization results for comparison
        if 'P_b' in openDssVals:
            openDssVals['P_b'][t, bus] = p
        elif 'P_c' in openDssVals and 'P_d' in openDssVals:
            if p >= 0:
                openDssVals['P_d'][t, bus] = p
                openDssVals['P_c'][t, bus] = 0.0
            else:
                openDssVals['P_d'][t, bus] = 0.0
                openDssVals['P_c'][t, bus] = -p
        openDssVals['B'][t, bus] = soc
        bat_id = dss.Storages.Next()
    return openDssVals

def get_opendss_total_circuitloss():
    losses = dss.Circuit.Losses()
    active_loss = losses[0]
    reactive_loss = losses[1]
    lossPowersDict_t = {
        'real_power_loss_t_kW': active_loss,
        'reactive_power_loss_t_kW': reactive_loss,
    }
    return lossPowersDict_t


def get_total_battery_power_opendss():
    vald_battery_real_power_t_kW = 0.0
    vald_battery_real_power_transaction_magnitude_t_kW = 0.0

    battery_names = dss.Storages.AllNames()
    for battery_name in battery_names:
        dss.Circuit.SetActiveElement(f"Storage.{battery_name}")
        battery_powers = dss.CktElement.Powers()
        real_power = -sum(battery_powers[::2])  # Negate to match injection convention

        vald_battery_real_power_t_kW += real_power
        vald_battery_real_power_transaction_magnitude_t_kW += abs(real_power)
    batteryPowersDict_t = {
        'battery_real_power_t_kW': vald_battery_real_power_t_kW,
        'battery_real_power_transaction_magnitude_t_kW': vald_battery_real_power_transaction_magnitude_t_kW,
    }

    return batteryPowersDict_t

def get_load_powers_opendss_powerflow():
    total_load_t_kW = 0.0
    total_load_t_kVAr = 0.0

    load_names = dss.Loads.AllNames()
    for load_name in load_names:
        dss.Circuit.SetActiveElement(f"Load.{load_name}")
        load_powers = dss.CktElement.Powers()
        total_load_t_kW += sum(load_powers[::2])
        total_load_t_kVAr += sum(load_powers[1::2])

    loadPowersDict_t = {
        'total_load_t_kW': total_load_t_kW,
        'total_load_t_kVAr': total_load_t_kVAr
    }

    return loadPowersDict_t

def get_pv_powers_opendss_powerflow():
    total_pv_t_kW = 0.0
    total_pv_t_kVAr = 0.0

    pv_names = dss.PVsystems.AllNames()
    for pv_name in pv_names:
        dss.Circuit.SetActiveElement(f"PVSystem.{pv_name}")
        pv_powers = dss.CktElement.Powers()
        total_pv_t_kW -= sum(pv_powers[::2])
        total_pv_t_kVAr -= sum(pv_powers[1::2])

    pvPowersDict_t = {
        'total_pv_t_kW': total_pv_t_kW,
        'total_pv_t_kVAr': total_pv_t_kVAr
    }

    return pvPowersDict_t

def edit_loads(data,t,P_base):
    load_id = dss.Loads.First()
    phase_map = {1: 'a', 2: 'b', 3: 'c'}
    while load_id > 0:
        load_name = dss.Loads.Name()
        dss.Circuit.SetActiveElement(f"Load.{load_name}")
        bus = dss.CktElement.BusNames()[0].split('.')[0]  # e.g., ["bus45", "3"]
        node_order = dss.CktElement.NodeOrder()
        nodes = [x for x in dict.fromkeys(node_order) if x != 0]
        p_kw = 0
        q_kvar = 0
        for node in nodes:
            ph = phase_map[node]
            p_kw += data['p_L'][t, bus, ph]*P_base / 1e3
            q_kvar += data['q_L'][t, bus, ph]*P_base / 1e3

            ## setting P and Q for Loads
            # dss.Text.Command(f"Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
            # print(f"Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
        dss.Text.Command(f"Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
        # print(f"Time Step {t}: hour={dss.Solution.Hour():02d}Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
        load_id = dss.Loads.Next()

def set_pv_controls(data, modelVals, t, P_base):
    pv_id = dss.PVsystems.First()
    phase_map = {1: 'a', 2: 'b', 3: 'c'}
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        dss.Circuit.SetActiveElement(f"PVSystem.{pv_name}")
        bus = dss.CktElement.BusNames()[0].split('.')[0]
        node_order = dss.CktElement.NodeOrder()
        nodes = [x for x in dict.fromkeys(node_order) if x != 0]
        p_pv = 0
        q_pv = 0
        for node_num in nodes:
            ph = phase_map[node_num]
            p_pv += modelVals['p_D'][t, bus, ph]*P_base/1e3
            q_pv += modelVals['q_D'][t, bus, ph]*P_base/1e3
            # print(f"Time Step {t}: Setting PV {pv_name} with p_pv={p_pv} and q_pv={q_pv}")
        dss.Text.Command(f"Edit PVSystem.{pv_name} Pmpp={p_pv} kvar={q_pv}")
        pv_id = dss.PVsystems.Next()

def set_battery_controls(data, modelVals, t, P_base):
    storage_id = dss.Storages.First()
    while storage_id > 0:
        storage_name = dss.Storages.Name()
        dss.Circuit.SetActiveElement(f"Storage.{storage_name}")
        bus = dss.CktElement.BusNames()[0].split('.')[0]
        if 'P_b' in modelVals:
            p_batt = modelVals['P_b'][t, bus]*P_base/1e3
        elif 'P_c' in modelVals and 'P_d' in modelVals:
            p_dis = modelVals['P_d'][t, bus]*P_base/1e3
            p_ch = modelVals['P_c'][t, bus]*P_base/1e3
            p_batt = p_dis - p_ch
        # print(f"Time Step {t}: Setting Battery {storage_name} with p_batt={Pnet_batt}")
        dss.Text.Command(f"Edit Storage.{storage_name} kw={p_batt} kvar = 0")
        storage_id = dss.Storages.Next()

def observe_load_powers_over_time(t):
    load_id = dss.Loads.First()
    while load_id > 0:
        load_name = dss.Loads.Name()
        dss.Circuit.SetActiveElement(f"Load.{load_name}")
        pq = dss.CktElement.Powers()
        nph = dss.CktElement.NumPhases()
        total_p = sum(pq[2*i] for i in range(nph))
        total_q = sum(pq[2*i+1] for i in range(nph))
        print(f"t={t} hour={dss.Solution.Hour():02d} load={load_name} actualP={total_p:.2f}kW actualQ={total_q:.2f}kvar (ratedP={dss.Loads.kW():.2f},ratedQ={dss.Loads.kvar():.2f})")
        load_id = dss.Loads.Next()

def get_total_nameplate_load_powers():
    p_kw = 0
    q_kvar = 0
    load_id = dss.Loads.First()
    while load_id > 0:
        load_name = dss.Loads.Name()
        dss.Circuit.SetActiveElement(f"Load.{load_name}")
        p_kw += dss.Loads.kW()
        q_kvar += dss.Loads.kvar()
        load_id = dss.Loads.Next()
    return p_kw, q_kvar

def get_total_nameplate_pv_powers():
    p_kw = 0
    pv_id = dss.PVsystems.First()
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        dss.Circuit.SetActiveElement(f"PVSystem.{pv_name}")
        p_kw += dss.PVsystems.Pmpp()
        pv_id = dss.PVsystems.Next()
    return p_kw

def initialize_current_angles(data,path, multi=False,start_step=1):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, path)

    dss.Text.Command("clear")
    dss.Text.Command(f"Redirect \"{script_path}\"")

    load_profile = [
        0.677, 0.6256, 0.6087, 0.5833, 0.58028, 0.6025, 0.657, 0.7477,
        0.832, 0.88, 0.94, 0.989, 0.985, 0.98, 0.9898, 0.999,
        1, 0.958, 0.936, 0.913, 0.876, 0.876, 0.828, 0.756
    ]
    load_mult = ' '.join(map(str, load_profile))
    if multi:
        dss.Text.Command(f'New Loadshape.loadshape npts=24 interval=1 mult=({load_mult})')
        dss.Text.Command(f"BatchEdit Load..* Daily=loadshape") ## use this as this gives better results
        dss.Text.Command("Set mode = Daily")
        dss.Text.Command("Set stepsize = 1h")
        dss.Text.Command("Set number = 1")
        dss.Text.Command(f"Set hour = {start_step-1}")

    openDssVals = {
        'I_mag': {},
        'I_ang': {},
    }

    for t in data['Tset']:
        # dss.Text.Command(f"Set hour = {t - 1}")
        dss.Text.Command("solve")
        if not dss.Solution.Converged():
            print(f"Power flow did not converge at time {t}")

        openDssVals = collect_opendss_linecurrents(openDssVals,t,data)

    return openDssVals

def run_opendss_validation(data, modelVals, path,multi=False,start_step=1):

    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, path)

    dss.Text.Command("clear")
    dss.Text.Command(f"Redirect \"{script_path}\"")

    load_profile = [
        0.677, 0.6256, 0.6087, 0.5833, 0.58028, 0.6025, 0.657, 0.7477,
        0.832, 0.88, 0.94, 0.989, 0.985, 0.98, 0.9898, 0.999,
        1, 0.958, 0.936, 0.913, 0.876, 0.876, 0.828, 0.756
    ]
    load_mult = ' '.join(map(str, load_profile))
    if multi:
        dss.Text.Command(f'New Loadshape.loadshape npts=24 interval=1 mult=({load_mult})')
        dss.Text.Command(f"BatchEdit Load..* Daily=loadshape") ## use this as this gives better results
        dss.Text.Command("Set mode = Daily")
        dss.Text.Command("Set stepsize = 1h")
        dss.Text.Command("Set number = 1")
        dss.Text.Command(f"Set hour = {start_step-1}")
    P_base = 1e6
    openDssVals = {
        'P_subs': {},
        'Q_subs': {},# (t, ph)
        'P': {},  # (t, fb, tb, ph)
        'Q': {},  # (t, fb, tb, ph)
        'v': {},
        'p_D': {},# (t, j, ph)
        'q_D': {},  # (t, j, ph)
        'B': {}, } # (t, j, ph)
    if 'P_b' in modelVals:
        openDssVals['P_b'] = {}
    elif 'P_c' in modelVals and 'P_d' in modelVals:
        openDssVals['P_c'] = {}
        openDssVals['P_d'] = {}

    # dss.Text.Command("BatchEdit PVSystem..* Daily=pvshape") ## doesnot give good results
    total_load_kw = 0
    total_load_kvar=0
    total_pv_kw=0
    total_pv_kvar = 0
    total_bat_real_power = 0
    total_bat_real_power_magnitude = 0
    total_p_loss = 0
    total_q_loss = 0

    for t in data['Tset']:
        # edit_loads(data,t,P_base)
        set_pv_controls(data, modelVals, t, P_base)## works ,tried with ieee_123 for all possible cases
        set_battery_controls(data,modelVals,t, P_base)
        # dss.Text.Command(f"Set hour = {t-1}")
        dss.Text.Command("solve")
        if not dss.Solution.Converged():
            print(f"Power flow did not converge at time {t}")

        total_load_t = get_load_powers_opendss_powerflow()
        pv_power_t = get_pv_powers_opendss_powerflow()
        battery_power_t = get_total_battery_power_opendss()
        total_loss_t = get_opendss_total_circuitloss()
        total_load_kw += total_load_t['total_load_t_kW']
        total_load_kvar += total_load_t['total_load_t_kVAr']
        total_pv_kw += pv_power_t['total_pv_t_kW']
        total_pv_kvar += pv_power_t['total_pv_t_kVAr']
        total_bat_real_power += battery_power_t['battery_real_power_t_kW']
        total_bat_real_power_magnitude += battery_power_t['battery_real_power_transaction_magnitude_t_kW']
        total_p_loss +=total_loss_t['real_power_loss_t_kW']
        total_q_loss += total_loss_t['reactive_power_loss_t_kW']

        openDssVals = collect_opendss_substationpower(openDssVals, t, P_base)
        openDssVals = collect_opendss_lineflows(openDssVals,t,data,P_base)
        openDssVals = collect_opendss_voltages(openDssVals,t)
        openDssVals = collect_opendss_pvPowers(openDssVals, t, P_base)
        openDssVals = collect_opendss_batteryresults(data,openDssVals, t, P_base)

    # ---------------------------------------------------------
    # 5) Return the results dictionary
    # ---------------------------------------------------------
    print(f"Total Substation Real Power Flows:{sum(openDssVals['P_subs'].values())} kW")
    print(f"Total substation Reactive Power Flows: {sum(openDssVals['Q_subs'].values())} kVar")
    print(f"total load KW : {total_load_kw}")
    print(f"total load KVAR : {total_load_kvar}")
    P,Q = get_total_nameplate_load_powers()
    print(f"total nameplate load power: {P} kW and {Q} kVAR")
    print(f"total PV KW : {total_pv_kw}, and {sum(openDssVals['p_D'].values())}")
    print(f"total PV KVAR : {total_pv_kvar}, and {sum(openDssVals['q_D'].values())}")
    print(f"total PV KW : {sum(openDssVals['p_D'].values()) * 1e3}")
    print(f"Total reactive power from PV Kvar: {sum(openDssVals['q_D'].values()) * 1e3}")
    print(f"Total battery real power: {total_bat_real_power}")
    print(f"Total battery real power magnitude: {total_bat_real_power_magnitude}")

    # Handle both linear and non-linear battery models for OpenDSS results
    if 'P_b' in openDssVals:
        print(f"Total battery power kW (P_b): {sum(openDssVals['P_b'].values())*1e3}")
    elif 'P_c' in openDssVals and 'P_d' in openDssVals:
        print(f"Total battery charging power kW (P_c): {sum(openDssVals['P_c'].values())*1e3}")
        print(f"Total battery discharging power kW (P_d): {sum(openDssVals['P_d'].values())*1e3}")
        print(f"Total battery net real power kW: {(sum(openDssVals['P_d'].values()) - sum(openDssVals['P_c'].values()))*1e3}, and {total_bat_real_power}")

    # print(f"Total Active Power:{-dss.Circuit.TotalPower()[0] / 1e3} MW")
    # print(f"Total Reactive Power:{-dss.Circuit.TotalPower()[1] / 1e3} Mvar")
    print(f"Total Active power loss from openDSS: {total_p_loss/1e3} kW")
    print(f"Total Reactive power loss from openDSS: {total_q_loss/1e3} kVar")
    return openDssVals

def all_time_highest_discrepancy(opendss,optimization,multi=False):
    Psubs_opendss = opendss['P_subs']
    Qsubs_opendss = opendss['Q_subs']
    Psubs_optimization = optimization['P_subs']
    Qsubs_optimization = optimization['Q_subs']
    P_vals_opendss = opendss['P']
    P_vals_optimization = optimization['P']
    Q_vals_opendss = opendss['Q']
    Q_vals_optimization = optimization['Q']
    V_vals_opendss = opendss['v']
    V_vals_optimization = optimization['v']

    # Overall maximum difference for each dictionary
    overall_max_psubs = max(np.max(np.abs(Psubs_opendss[key] - Psubs_optimization[key])) for key in Psubs_opendss.keys()& Psubs_optimization.keys())
    overall_max_qsubs = max(np.max(np.abs(Qsubs_opendss[key] - Qsubs_optimization[key])) for key in Qsubs_opendss.keys()& Qsubs_optimization.keys())
    overall_max_p = max(np.max(np.abs(P_vals_opendss[key] - P_vals_optimization[key])) for key in P_vals_opendss.keys() & P_vals_optimization.keys())
    overall_max_q = max(np.max(np.abs(Q_vals_opendss[key] - Q_vals_optimization[key])) for key in Q_vals_opendss.keys() & Q_vals_optimization.keys())
    overall_max_v = max(np.max(np.abs(V_vals_opendss[key] - np.sqrt(V_vals_optimization[key]))) for key in V_vals_opendss.keys() & V_vals_optimization.keys())

    print(f"Overall maximum difference for psubs arrays: {overall_max_psubs*1e3} kW")
    print(f"Overall maximum difference for qsubs arrays: {overall_max_qsubs*1e3} kVar")
    print(f"Overall maximum difference for p arrays: {overall_max_p*1e3} kW")
    print(f"Overall maximum difference for q arrays: {overall_max_q*1e3} kVar")
    print(f"Overall maximum difference for v arrays: {overall_max_v}")

    if multi:
        # B_vals_opendss = opendss['B']
        # B_vals_optimization = optimization['B']
        p_D_vals_opendss = opendss['p_D']
        p_D_vals_optimization = optimization['p_D']
        q_D_vals_opendss = opendss['q_D']
        q_D_vals_optimization = optimization['q_D']
        P_c_vals_opendss = opendss['P_c']
        P_c_vals_optimization = optimization['P_c']
        P_d_vals_opendss = opendss['P_d']
        P_d_vals_optimization = optimization['P_d']

        # overall_max_b = max(np.max(np.abs(B_vals_opendss[key] - B_vals_optimization[key])) for key in B_vals_opendss.keys())
        overall_max_p_D = max(np.max(np.abs(p_D_vals_opendss[key] - p_D_vals_optimization[key])) for key in p_D_vals_opendss.keys())
        overall_max_q_D = max(np.max(np.abs(q_D_vals_opendss[key] - q_D_vals_optimization[key])) for key in q_D_vals_opendss.keys())
        overall_max_P_c = max(np.max(np.abs(P_c_vals_opendss[key] - P_c_vals_optimization[key])) for key in P_c_vals_opendss.keys())
        overall_max_P_d = max(np.max(np.abs(P_d_vals_opendss[key] - P_d_vals_optimization[key])) for key in P_d_vals_opendss.keys())

        # print("Overall maximum difference for b arrays:", overall_max_b)
        print(f"Overall maximum difference for p_D arrays: {overall_max_p_D} kW")
        print(f"Overall maximum difference for q_D arrays: {overall_max_q_D} kVar")
        print(f"Overall maximum difference for P_c arrays: {overall_max_P_c} kW")
        print(f"Overall maximum difference for P_d arrays: {overall_max_P_d} kW")

    total_loss_p = sum(Psubs_opendss[key] - Psubs_optimization[key] for key in Psubs_opendss.keys()& Psubs_optimization.keys())
    total_loss_q = sum(Qsubs_opendss[key] - Qsubs_optimization[key] for key in Qsubs_opendss.keys()& Qsubs_optimization.keys())

    # print(f"Total P loss: {total_loss_p*1e3} kW")
    # print(f"Total Q loss: {total_loss_q*1e3} kVar")


