import numpy as np
import opendssdirect as dss
import os
import networkx as nx
import json

# Path to your JSON file
json_path = "dssconverter/bus_index_map.json"

# Load the JSON data
with open(json_path, "r") as f:
    map_names_to_index = json.load(f)

# map_index_to_names = {v: k for k, v in map_names_to_index.items()}
# def source() -> str:
#     """source bus of the circuit.
#
#     Returns:
#         str: returns the source bus of the circuit
#     """
#     # typically the first bus is the source bus
#     dss.Vsources.First()
#     return dss.CktElement.BusNames()[0].split(".")[0]
#
# def get_bus_names() -> list[str]:
#     """Access all the bus (node) names from the circuit
#
#     Returns:
#         list[str]: list of all the bus names
#     """
#
#     flag = dss.PDElements.First()
#     branches = []
#     while flag:
#         element_type = dss.CktElement.Name().lower().split(".")[0]
#         if element_type not in ["line", "transformer", "reactor"]:
#             flag = dss.PDElements.Next()
#             continue
#         bus1 = dss.CktElement.BusNames()[0].split(".")[0]
#         bus2 = dss.CktElement.BusNames()[1].split(".")[0]
#         branches.append((bus1, bus2))
#         dss.Circuit.SetActiveBus(bus2)
#         flag = dss.PDElements.Next()
#     g = nx.Graph()
#     g.add_edges_from(set(branches))
#     source_bus = source()
#     node_list = nx.dfs_preorder_nodes(g, source_bus)
#     node_list = list(node_list)
#     return node_list
#
# def bus_names_to_index_map(bus_names) -> dict[str, int]:
#     """each of the bus mapped to its corresponding index in the bus names list
#
#     Returns:
#         dict[str,int]: dictionary with key as bus names and value as its index
#     """
#     _map = {bus: index + 1 for index, bus in enumerate(bus_names)}
#     return _map

def collect_opendss_substationpower(openDssVals,t,P_base):
    ## for some reason this is not working
    # dss.Circuit.SetActiveElement("Vsource.src")  # Use actual Vsource name
    # vs_powers = dss.CktElement.Powers()
    # for idx in range(dss.CktElement.NumPhases()):
    #     ph = ['a', 'b', 'c'][idx]
    #     p = -vs_powers[2 * idx] * 1000 / P_base
    #     q = -vs_powers[2 * idx + 1] * 1000 / P_base
    #     openDssVals['P_subs'][(t, ph)] = p
    #     openDssVals['Q_subs'][(t, ph)] = q

    ## taking substation power as the power flowing in the first line
    line_id = dss.Lines.First()
    while line_id == 1:
        line_name = dss.Lines.Name()
        dss.Circuit.SetActiveElement(f"Line.{line_name}")
        busnames = dss.CktElement.BusNames()
        line_powers = dss.CktElement.Powers()
        ph_number = busnames[0].split('.')[1:]
        phases = [int(x) - 1 for x in ph_number] if ph_number else [0, 1, 2]
        ph_letters = [{0: 'a', 1: 'b', 2: 'c'}[n] for n in phases]
        for ph_idx, ph in enumerate(ph_letters):
            p = line_powers[2 * ph_idx] * 1000 / P_base
            q = line_powers[2 * ph_idx + 1] * 1000 / P_base

            openDssVals['P_subs'][t, ph] = p
            openDssVals['Q_subs'][t, ph] = q

        line_id = dss.Lines.Next()

    return openDssVals

def collect_opendss_lineflows(openDssVals,t,P_base):
    line_id = dss.Lines.First()
    while line_id > 0:
        line_name = dss.Lines.Name()
        dss.Circuit.SetActiveElement(f"Line.{line_name}")
        busnames = dss.CktElement.BusNames()
        line_powers = dss.CktElement.Powers()
        ph_number = busnames[0].split('.')[1:]
        phases = [int(x) - 1 for x in ph_number] if ph_number else [0, 1, 2]
        ph_letters = [{0: 'a', 1: 'b', 2: 'c'}[n] for n in phases]
        fb = map_names_to_index[busnames[0].split('.')[0]]
        tb =  map_names_to_index[busnames[1].split('.')[0]]
        for ph_idx, ph in enumerate(ph_letters):
            p = line_powers[2 * ph_idx] * 1000 / P_base
            q = line_powers[2 * ph_idx + 1] * 1000 / P_base

            openDssVals['P'][t,(fb,tb),ph] = p
            openDssVals['Q'][t,(fb,tb),ph] = q

        line_id = dss.Lines.Next()

    return openDssVals

def collect_opendss_voltages(openDssVals,t): # Activate all buses
    phase_to_idx = {'a': 1, 'b': 2, 'c': 3}
    phases = ['a', 'b', 'c']
    for ph in phases:
        ph_num = phase_to_idx[ph]
        node_names = dss.Circuit.AllNodeNamesByPhase(ph_num)
        vmag_pu = dss.Circuit.AllNodeVmagPUByPhase(ph_num)

        for i_node, node_name in enumerate(node_names):
            bus_id = map_names_to_index[node_name.split('.')[0]]
            openDssVals['v'][(t, bus_id, ph)] = vmag_pu[i_node]
    return openDssVals

def collect_opendss_pvPowers(openDssVals,t, P_base):
    pv_id = dss.PVsystems.First()
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        dss.Circuit.SetActiveElement(f"PVsystem.{pv_name}")
        bus_ph = dss.CktElement.BusNames()[0].split('.')  # e.g., ["bus123", "1", "2"]
        bus = map_names_to_index[bus_ph[0]]
        ph_nodes = bus_ph[1:]
        phases = [int(x) - 1 for x in ph_nodes] if ph_nodes else [0, 1, 2]# e.g., ["1", "2"] for phases a, b
        for phase in phases:
            ph = {0: 'a', 1: 'b', 2: 'c'}[phase]
            p = -dss.CktElement.Powers()[0] * 1000 / P_base
            q = -dss.CktElement.Powers()[1] * 1000 / P_base
            openDssVals['p_D'][(t, bus, ph)] = p
            openDssVals['q_D'][(t, bus, ph)] = q
        pv_id = dss.PVsystems.Next()
    return openDssVals

def collect_opendss_batteryresults(data,openDssVals,t, P_base):
    bat_id = dss.Storages.First()
    while bat_id > 0:
        batt_name = dss.Storages.Name()
        dss.Circuit.SetActiveElement(f"Storage.{batt_name}")
        bus_ph = dss.CktElement.BusNames()[0].split('.')   # e.g., ["bus45", "3"]
        bus = map_names_to_index[bus_ph[0]]
        phases = [int(x) - 1 for x in bus_ph[1:]] if bus_ph[1:] else [0, 1, 2]
        p = -dss.CktElement.Powers()[0] * 1000 / P_base
        soc = dss.Storages.puSOC() ## multiplying by rated to match optimization results for comparison
        for phase in phases:
            ph = "abc"[phase]
            if p >= 0:
                openDssVals['P_d'][(t, bus, ph)] = p
                openDssVals['P_c'][(t, bus, ph)] = 0.0
            else:
                openDssVals['P_d'][(t, bus, ph)] = 0.0
                openDssVals['P_c'][(t, bus, ph)] = -p
            openDssVals['B'][(t, bus, ph)] = soc * data['p_B'][bus, ph]
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
        real_power = -battery_powers[0]  # Negate to match injection convention

        vald_battery_real_power_t_kW += real_power
        vald_battery_real_power_transaction_magnitude_t_kW += abs(real_power)
    batteryPowersDict_t = {
        'vald_battery_real_power_t_kW': vald_battery_real_power_t_kW,
        'vald_battery_real_power_transaction_magnitude_t_kW': vald_battery_real_power_transaction_magnitude_t_kW,
    }

    return batteryPowersDict_t

def get_load_powers_opendss_powerflow():
    total_load_t_kW = 0.0
    total_load_t_kVAr = 0.0

    load_names = dss.Loads.AllNames()
    for load_name in load_names:
        dss.Circuit.SetActiveElement(f"Load.{load_name}")
        load_powers = dss.CktElement.Powers()
        total_load_t_kW += load_powers[0]
        total_load_t_kVAr += load_powers[1]

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
        total_pv_t_kW -= pv_powers[0]
        total_pv_t_kVAr -= pv_powers[1]

    pvPowersDict_t = {
        'total_pv_t_kW': total_pv_t_kW,
        'total_pv_t_kVAr': total_pv_t_kVAr
    }

    return pvPowersDict_t

def edit_loads(data,t,P_base):
    load_id = dss.Loads.First()
    while load_id > 0:
        load_name = dss.Loads.Name()
        # Split the string by underscores
        parts = dss.CktElement.BusNames()[0].split('.')

        # Extract the desired values
        bus = parts[0]  # '3'
        phases = [int(x) - 1 for x in parts[1:]] if parts[1:] else [0, 1, 2]
        i = map_names_to_index[bus]
        for phase in phases:
            ph = "abc"[phase]
            p_kw = data['p_L'][(t, i, ph)] * (P_base / 1000)
            q_kvar = data['q_L'][(t, i, ph)] * (P_base / 1000)

            ## setting P and Q for Loads
            dss.Text.Command(f"Edit Load.{load_name} kw={p_kw} kvar={q_kvar}")
            # print(f"Time Step {t}: Setting load {load_name} with kw: {p_kw} and kvar: {q_kvar}")

        load_id = dss.Loads.Next()


def set_pv_controls(data, modelVals,t, P_base):
    pv_id = dss.PVsystems.First()
    while pv_id > 0:
        pv_name = dss.PVsystems.Name()
        # Split the string by underscores
        parts = dss.CktElement.BusNames()[0].split('.')

        bus = parts[0]  # '3'
        phases = [int(x) - 1 for x in parts[1:]] if parts[1:] else [0, 1, 2]

        # 'a'
        i = map_names_to_index[bus]
        for phase in phases:
            ph = "abc"[phase]
            p_pv = data['p_D'][(t, i, ph)] * (P_base / 1000)  # kW
            q_pv = modelVals['q_D'][(t, i, ph)] * (P_base / 1000)  # kVar

            dss.Text.Command(f"Edit PVSystem.{pv_name} Pmpp={p_pv} kvar={q_pv}")
            # print(f"Time Step {t}: Setting PV {pv_name} with kw: {p_pv} and kvar : {q_pv}")

        pv_id = dss.PVsystems.Next()
    # gen_id = dss.Generators.First()
    # while gen_id > 0:
    #     gen_name = dss.Generators.Name()
    #     # Split the string by underscores
    #     parts = dss.CktElement.BusNames()[0].split('.')
    #
    #     bus = parts[0]  # '3'
    #     phases = [int(x) - 1 for x in parts[1:]] if parts[1:] else [0, 1, 2]
    #
    #     # 'a'
    #     i = map_names_to_index[bus]
    #     for phase in phases:
    #         ph = "abc"[phase]
    #         p_pv = data['p_D'][(t, i, ph)] * (P_base / 1000)  # kW
    #         q_pv = modelVals['q_D'][(t, i, ph)] * (P_base / 1000)  # kVar
    #
    #         dss.Text.Command(f"Edit Generator.{gen_name} kw={p_pv} kvar={q_pv}")
    #         # print(f"Time Step {t}: Setting PV {pv_name} with kw: {p_pv} and kvar : {q_pv}")
    #
    #     gen_id = dss.Generators.Next()

def set_battery_controls(data, modelVals,t, P_base):
    storage_id = dss.Storages.First()
    while storage_id > 0:
        storage_name = dss.Storages.Name()
        parts = dss.CktElement.BusNames()[0].split('.')
        bus = parts[0]  # '3'
        phases = [int(x) - 1 for x in parts[1:]] if parts[1:] else [0, 1, 2]
        i =  map_names_to_index[bus]
        for phase in phases:
            ph = "abc"[phase]
            p_dis = modelVals['P_d'][(t, i, ph)] * (P_base / 1000)
            p_chg = modelVals['P_c'][(t, i, ph)] * (P_base / 1000)
            Pnet_batt = (p_dis - p_chg)
            dss.Text.Command(f"Edit Storage.{storage_name} kw={Pnet_batt}")
            # print(f"Time Step {t}: Setting Battery {storage_name} with kw: {Pnet_batt}")

        storage_id = dss.Storages.Next()

def run_opendss_validation(data, modelVals):
    # Save the OpenDSS script in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, "..","rawData","test","dss_scripts","Master.dss")
    # ---------------------------------------------------------
    # 1) Initialize a results dictionary in the same format as modelVals
    # ---------------------------------------------------------

    P_base = 1e6
    openDssVals = {
        'P_subs': {},
        'Q_subs': {},# (t, ph)
        'P': {},  # (t, (fb, tb), ph)
        'Q': {},  # (t, (fb, tb), ph)
        'v': {},
        'p_D': {},# (t, j, ph)
        'q_D': {},  # (t, j, ph)
        'P_c': {},  # (t, j, ph)
        'P_d': {},  # (t, j, ph)
        'B': {},  # (t, j, ph)
    }

    ## Now doing the time series loop
    dss.Text.Command("clear")
    # Redirect OpenDSS to use the generated script
    dss.Text.Command(f"Redirect \"{script_path}\"")
    total_load_kw = 0
    total_load_kvar=0
    total_pv_kw=0
    total_p_loss = 0
    total_q_loss = 0
    for t in data['Tset']:
        edit_loads(data,t,P_base)
        set_pv_controls(data,modelVals,t, P_base)
        set_battery_controls(data,modelVals,t, P_base)
        # dss.Text.Command("Set ControlMode = OFF")
        dss.Text.Command("Batchedit RegControl..* enabled=false")
        dss.Text.Command("Batchedit CapControl..* enabled=false")
        dss.Text.Command("Batchedit Capacitor..* enabled=false")
        dss.Text.Command("solve")

        total_load_t = get_load_powers_opendss_powerflow()
        pv_power_t = get_pv_powers_opendss_powerflow()
        battery_power_t = get_total_battery_power_opendss()
        total_loss_t = get_opendss_total_circuitloss()
        total_load_kw += total_load_t['total_load_t_kW']
        total_load_kvar += total_load_t['total_load_t_kVAr']
        total_pv_kw += pv_power_t['total_pv_t_kW']
        total_p_loss +=total_loss_t['real_power_loss_t_kW']
        total_q_loss += total_loss_t['reactive_power_loss_t_kW']

        openDssVals = collect_opendss_substationpower(openDssVals, t, P_base)
        openDssVals = collect_opendss_lineflows(openDssVals,t,P_base)
        openDssVals = collect_opendss_voltages(openDssVals,t)
        openDssVals = collect_opendss_pvPowers(openDssVals, t, P_base)
        openDssVals = collect_opendss_batteryresults(data,openDssVals, t, P_base)

    # ---------------------------------------------------------
    # 5) Return the results dictionary
    # ---------------------------------------------------------
    print(f"total load KW : {total_load_kw}")
    print(f"total load KVAR : {total_load_kvar}")
    print(f"total PV KW : {total_pv_kw}")
    print(f"Total Active power loss from openDSS: {total_p_loss/1000}")
    print(f"Total Reactive power loss from openDSS: {total_q_loss/1000}")
    return openDssVals

def all_time_highest_discrepancy(opendss,optimization):
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
    B_vals_opendss = opendss['B']
    B_vals_optimization = optimization['B']
    # p_D_vals_opendss = opendss['p_D']
    # p_D_vals_optimization = optimization['p_D']
    q_D_vals_opendss = opendss['q_D']
    q_D_vals_optimization = optimization['q_D']
    P_c_vals_opendss = opendss['P_c']
    P_c_vals_optimization = optimization['P_c']
    P_d_vals_opendss = opendss['P_d']
    P_d_vals_optimization = optimization['P_d']

    # Overall maximum difference for each dictionary
    overall_max_psubs = max(np.max(np.abs(Psubs_opendss[key] - Psubs_optimization[key])) for key in Psubs_opendss.keys())
    overall_max_qsubs = max(np.max(np.abs(Qsubs_opendss[key] - Qsubs_optimization[key])) for key in Qsubs_opendss.keys())
    # overall_max_p = max(np.max(np.abs(P_vals_opendss[key] - P_vals_optimization[key])) for key in P_vals_opendss.keys())
    # overall_max_q = max(np.max(np.abs(Q_vals_opendss[key] - Q_vals_optimization[key])) for key in Q_vals_opendss.keys())
    overall_max_v = max(np.max(np.abs(V_vals_opendss[key] - V_vals_optimization[key])) for key in V_vals_opendss.keys())
    overall_max_b = max(np.max(np.abs(B_vals_opendss[key] - B_vals_optimization[key])) for key in B_vals_opendss.keys())
    # overall_max_p_D = max(np.max(np.abs(p_D_vals_opendss[key] - p_D_vals_optimization[key])) for key in p_D_vals_opendss.keys())
    overall_max_q_D = max(np.max(np.abs(q_D_vals_opendss[key] - q_D_vals_optimization[key])) for key in q_D_vals_opendss.keys())
    overall_max_P_c = max(np.max(np.abs(P_c_vals_opendss[key] - P_c_vals_optimization[key])) for key in P_c_vals_opendss.keys())
    overall_max_P_d = max(np.max(np.abs(P_d_vals_opendss[key] - P_d_vals_optimization[key])) for key in P_d_vals_opendss.keys())

    print("Overall maximum difference for psubs arrays:", overall_max_psubs)
    print("Overall maximum difference for qsubs arrays:", overall_max_qsubs)
    # print("Overall maximum difference for p arrays:", overall_max_p)
    # print("Overall maximum difference for q arrays:", overall_max_q)
    print("Overall maximum difference for v arrays:", overall_max_v)
    print("Overall maximum difference for b arrays:", overall_max_b)
    # print("Overall maximum difference for p_D arrays:", overall_max_p_D)
    print("Overall maximum difference for q_D arrays:", overall_max_q_D)
    print("Overall maximum difference for P_c arrays:", overall_max_P_c)
    print("Overall maximum difference for P_d arrays:", overall_max_P_d)

