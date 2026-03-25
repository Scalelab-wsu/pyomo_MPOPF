import networkx as nx

###########################
# 3) Build the graph from data
###########################
def build_graph_from_data(full_data):
    """
    Constructs a directed graph from the 'full_data' dictionary and branch_list.
    """
    g = nx.DiGraph()
    # Add nodes
    for bus_id in full_data["Nset"]:
        g.add_node(bus_id)
    # Add edges from branch_list
    for branch in full_data["Lset"]:
        fb = branch[0]
        tb = branch[1]
        g.add_edge(fb, tb)
    return g

###########################
# 4) Remove cross-area edges and insert dummy nodes
###########################
def remove_inter_area_edges(g, area_info,full_data):
    dummy_keys = ['aa', 'ab', 'ac', 'bb', 'bc', 'cc']
    r = full_data['r']
    x = full_data['x']

    # Initialize dummy_edge_r and dummy_edge_x as nested dicts
    dummy_edge_r = {area: {key: {} for key in dummy_keys} for area in area_info.keys()}
    dummy_edge_x = {area: {key: {} for key in dummy_keys} for area in area_info.keys()}

    # Map each created dummy edge -> the original edge (fb,tb) it came from
    dummy_edge_parent = {}

    for area in area_info.keys():
        for i, fb in enumerate(area_info[area]["down_global_node_id"]):
            down_area = area_info[area]["down_areas"][i]
            tb = area_info[down_area]["up_global_node_id"][0]
            dummy1 = area_info[area]["down_local_node_id"][i]
            dummy2 = area_info[down_area]["up_local_node_id"][0]

            if g.has_edge(fb, tb):
                # Assign half impedances to new edges
                for key in dummy_keys:
                    # Check if the original edge has impedance data
                    if (fb, tb) in full_data['Lset']:
                        dummy_r_value = r[key][(fb, tb)] / 2
                        dummy_x_value = x[key][(fb, tb)] / 2
                    else:
                        print(f"Warning: Impedance data for edge ({fb}, {tb}) not found in 'r[{key}]' or 'x[{key}]'. Assigning 0.")
                        dummy_r_value = 0
                        dummy_x_value = 0
                    # Assign to new edges
                    dummy_edge_r[area][key][(fb, dummy1)] = dummy_r_value
                    dummy_edge_r[down_area][key][(dummy2, tb)] = dummy_r_value
                    dummy_edge_x[area][key][(fb, dummy1)] = dummy_x_value
                    dummy_edge_x[down_area][key][(dummy2, tb)] = dummy_x_value

                # Remember parent edge for I_ang inheritance
                dummy_edge_parent[(fb, dummy1)] = (fb, tb)
                dummy_edge_parent[(dummy2, tb)] = (fb, tb)

                # Remove the original edge
                g.remove_edge(fb, tb)

                # Add edges with dummy bus
                g.add_edge(fb, dummy1)
                g.add_edge(dummy2, tb)

    return g, dummy_edge_r, dummy_edge_x, dummy_edge_parent


###########################
# 6) Build sub-area data
###########################
def build_area_data(full_data, area_name, sg_local, dummy_r,dummy_x, dummy_edge_parent=None):

    # The sub-area's nodes and edges
    Nset_area = sg_local.nodes()
    Lset_area = list(sg_local.edges())

    # Subset Dset and Bset
    Dset_area = [gen_id for gen_id in full_data["Dset"] if gen_id in Nset_area]
    Bset_area = [bat_id for bat_id in full_data["Bset"] if bat_id in Nset_area]

    # Filter p_L, q_L, etc., keeping only those in Nset_area
    p_L_area = {
        key: full_data["p_L"][key]
        for key in full_data["p_L"]
        if key[1] in Nset_area
    }
    dummy_nodes = set(Nset_area) - set(full_data['Nset'])
    dummy_nodes_phases = {j:['a','b','c'] for j in dummy_nodes}
    p_L_area_dummy  ={(t,i,ph): 0 for t in full_data["Tset"] for i in dummy_nodes for ph in full_data['phases']}
    p_L_area.update(p_L_area_dummy)
    q_L_area = {
        key: full_data["q_L"][key]
        for key in full_data["q_L"]
        if key[1] in Nset_area
    }
    q_L_area_dummy = {(t, i, ph): 0 for t in full_data["Tset"] for i in dummy_nodes for ph in full_data['phases']}
    q_L_area.update(q_L_area_dummy)
    p_D_area = {
        key: full_data["p_D"][key]
        for key in full_data["p_D"]
        if key[1] in Dset_area
    }
    s_D_area = {
        key: full_data["s_D"][key]
        for key in full_data["s_D"]
        if key[0] in Dset_area
    }
    p_B_area = {
        key: full_data["p_B"][key]
        for key in full_data["p_B"].keys()
        if key in Bset_area
    }
    s_B_area = {
        key: full_data["s_B"][key]
        for key in full_data["s_B"].keys()
        if key in Bset_area
    }
    eta_c_area = {
        key: full_data["eta_c"][key]
        for key in full_data["eta_c"]
        if key[0] in Bset_area
    }
    eta_d_area = {
        key: full_data["eta_d"][key]
        for key in full_data["eta_d"]
        if key[0] in Bset_area
    }
    bmin_area = {
        key: full_data["bmin"][key]
        for key in full_data["bmin"].keys()
        if key in Bset_area
    }
    bmax_area = {
        key: full_data["bmax"][key]
        for key in full_data["bmax"].keys()
        if key in Bset_area
    }
    b0_area = {
        key: full_data["b0"][key]
        for key in full_data["b0"].keys()
        if key in Bset_area
    }

    # Slice v_min, v_max, v_swing
    v_min_area = {i: full_data["v_min"][i] for i in Nset_area if i in full_data["v_min"]}
    v_min_area_dummy = {i:0.95 for i in dummy_nodes}
    v_min_area.update(v_min_area_dummy)
    v_max_area = {i: full_data["v_max"][i] for i in Nset_area if i in full_data["v_max"]}
    v_max_area_dummy = {i: 1.05 for i in dummy_nodes}
    v_max_area.update(v_max_area_dummy)
    fb = [branch[0] for branch in Lset_area]
    tb = [branch[1] for branch in Lset_area]
    substation_bus = list(set(fb) - set(tb))
    # v_swing_area = {(i,ph): 1.05 for i in substation_bus for ph in full_data['phases']}
    if area_name == 'area1':
        v_swing_area = {(t,i,ph): 1.05 for t in full_data["Tset"] for i in substation_bus for ph in full_data['phases']}
    else:
        v_swing_area = {(t,i, ph): 1.05 for t in full_data["Tset"] for i in substation_bus for ph in full_data['phases']}
    coupling = ['aa','ab','ac','bb','bc','cc']
    dummy_edges = set(set(Lset_area) - set(full_data['Lset']))
    dummy_edges_phases = {edge:['a','b','c'] for edge in dummy_edges}

    # I_ang: real edges from full_data, dummy edges inherit from their parent edge
    I_ang_full = full_data.get("I_ang", {})
    I_ang_area = {k: v for k, v in I_ang_full.items() if (k[1], k[2]) in Lset_area}

    for t in full_data["Tset"]:
        for (i, j), phs in dummy_edges_phases.items():
            parent = dummy_edge_parent.get((i, j), None)
            for ph in phs:
                if parent is None:
                    I_ang_area[(t, i, j, ph)] = 0.0
                else:
                    I_ang_area[(t, i, j, ph)] = I_ang_full.get((t, parent[0], parent[1], ph), 0.0)

    r={}
    x={}
    for coup in coupling:
        r[coup] = {}
        x[coup] = {}
        for (i, j) in Lset_area:
            if (i, j) in full_data['Lset']:
                r[coup][(i, j)] = full_data['r'][coup][(i, j)]
                x[coup][(i, j)] = full_data['x'][coup][(i, j)]
            else:
                r[coup][(i, j)] = dummy_r[area_name][coup][i, j]
                x[coup][(i, j)] = dummy_x[area_name][coup][i, j]

    r["ba"] = r["ab"]
    r["ca"] = r["ac"]
    r["cb"] = r["bc"]

    x["ba"] = x["ab"]
    x["ca"] = x["ac"]
    x["cb"] = x["bc"]

    # Now, create the area-level data dictionary
    data_area = {
        "Nset": Nset_area,
        "Lset": Lset_area,
        "Dset": Dset_area,
        "Bset": Bset_area,
        "substationBus": substation_bus,
        "T": full_data["T"],
        "Tset": full_data["Tset"],
        "phases": full_data["phases"],
        'bus_phases': {**{key:value for key, value in full_data['bus_phases'].items() if key in Nset_area}, **dummy_nodes_phases},
        'branch_phases': {**{key:value for key, value in full_data['branch_phases'].items() if key in Lset_area}, **dummy_edges_phases},
        'gen_phases': {key:value for key, value in full_data['gen_phases'].items() if key in Dset_area},
        'bat_phases': {key:value for key, value in full_data['bat_phases'].items() if key in Bset_area},
        'I_ang' : I_ang_area,
        "r": r,
        "x": x,
        "p_L": p_L_area,
        "q_L": q_L_area,
        "v_min": v_min_area,
        "v_max": v_max_area,
        "v_swing": v_swing_area,
        "p_D": p_D_area,
        "s_D": s_D_area,
        "eta_c": eta_c_area,
        "eta_d": eta_d_area,
        "bmin": bmin_area,
        "bmax": bmax_area,
        "p_B": p_B_area,
        "s_B": s_B_area,
        "loadshape": full_data["loadshape"],
        "pvshape": full_data["pvshape"],
        "b0": b0_area,
        "costshape": full_data["costshape"],
    }
    return data_area

###########################
# 7) Main function
###########################
def split_data_into_areas(full_data,area_info):
    # ----------------------------
    # Step 2: Build the graph from data
    # ----------------------------
    g = build_graph_from_data(full_data)

    # ----------------------------
    # Step 3: Remove cross-area edges and insert dummy nodes with half impedances
    # ----------------------------
    g, dummy_r, dummy_x, dummy_edge_parent = remove_inter_area_edges(g, area_info, full_data)

    # ----------------------------
    # Step 5: Identify subgraphs
    # ----------------------------
    subgraphs = [g.subgraph(c).copy() for c in nx.weakly_connected_components(g)]

    # For each area, find the subgraph containing its up_global_node_id[0]
    area_subgraphs = {}
    for area_name, info in area_info.items():
        root_node = info["up_local_node_id"][0]
        sg = next((sg for sg in subgraphs if root_node in sg), None)
        if sg is not None:
            area_subgraphs[area_name] = sg
        else:
            print(f"Warning: No subgraph found containing root node {root_node} for area {area_name}.")

    # ----------------------------
    # Step 6: Build area-level data dictionaries
    # ----------------------------
    data_by_area = {}
    for area_name, sg_local in area_subgraphs.items():
        data_area = build_area_data(full_data, area_name, sg_local,dummy_r,dummy_x, dummy_edge_parent)
        data_by_area[area_name] = data_area

    return data_by_area

