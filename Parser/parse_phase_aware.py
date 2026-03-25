# data_parser.py
import pandas as pd
import os
from scipy.sparse import csr_matrix
import numpy as np
import networkx as nx
from collections import defaultdict

def parse_all_data_phase_aware(bus, branch, gen=None, bat=None, loadshape=None, pvshape=None, price=None,start_step = 1, n_steps = 24):
    T = n_steps
    Tset = np.arange(start_step, start_step + n_steps)
    phases = ['a', 'b', 'c']

    ## parsing profiles_data
    if loadshape is not None:
        loadshape_dict = dict(zip(loadshape['time'], loadshape['M']))
        loadshape = {t: loadshape_dict[t] for t in Tset}
    else:
        loadshape = {t: 1 for t in Tset}

    if pvshape is not None:
        pvshape_dict = dict(zip(pvshape['time'], pvshape['M']))
        pvshape = {t: pvshape_dict[t] for t in Tset}
    else:
        pvshape = {t: 1 for t in Tset}

    if price is not None:
        costshape = {t: price[t - 1] for t in Tset}
    else:
        costshape = {t: 1 for t in Tset}

    ## parsing bus_data
    # substationBus = list(set(branch['fb']) - set(branch['tb']))
    bus['name'] = bus['name'].astype(str)
    substationBus = [bus.loc[bus.bus_type == "SWING", "name"].values[0]]
    bus_set = set(bus['name'])  # Directly convert column to set
    bus_lookup = bus.set_index('name')

    # Extract phase information for each bus
    bus_phases = {i: list(bus_lookup.at[i, 'phases']) for i in bus_set}

    p_L = {(t, i, ph): bus_lookup.at[i, f"pl_{ph}"] * loadshape[t] for t in Tset for i in bus_set for ph in bus_phases[i]}
    q_L = {(t, i, ph): bus_lookup.at[i, f"ql_{ph}"] * loadshape[t] for t in Tset for i in bus_set for ph in bus_phases[i]}
    v_min = {i: bus_lookup.at[i, "v_min"] for i in bus_set}
    v_max = {i: bus_lookup.at[i, "v_max"] for i in bus_set}
    v_swing = {(t, i, ph): bus_lookup.at[i, f"v_{ph}"] for t in Tset for i in substationBus for ph in bus_phases[i]}

    ## parsing branch_data
    branch['from_name'] = branch['from_name'].astype(str)
    branch['to_name'] = branch['to_name'].astype(str)
    branch = branch.loc[branch.status != 'OPEN']
    branch_set = set(zip(branch['from_name'], branch['to_name']))

    # Extract phase information for each branch
    branch_lookup = branch.set_index(['from_name', 'to_name'])
    branch_phases = {(fb, tb): list(branch_lookup.at[(fb, tb), 'phases']) for fb, tb in branch_set}

    # ## this gives the positive flows
    g = nx.Graph()
    g.add_edges_from(branch_set)
    edges = np.array(list(nx.dfs_edges(g, source=substationBus[0])))
    branch_set = set(zip(edges[:, 0], edges[:, 1]))
    phase_pairs = ["aa", "ab", "ac", "bb", "bc", "cc"]
    r = {pp: defaultdict(float) for pp in phase_pairs}
    x = {pp: defaultdict(float) for pp in phase_pairs}

    # ## see the bfs edges and nodes
    bfs_tree = nx.bfs_tree(g, source=substationBus[0])

    # Extract the nodes from the BFS tree in the order they were visited
    bfs_nodes = list(bfs_tree.nodes())

    # Extract the BFS edges in the order they were traversed
    bfs_edges = list(bfs_tree.edges())

    # Use itertuples() to unpack each row in one go, which is faster than indexing by [i]
    for row in branch.itertuples(index=False):
        # row is a namedtuple like (from_name, to_name, raa, rab, …, xcc)
        fb = row.from_name
        tb = row.to_name

        # We know the order of columns in the DataFrame. Suppose they are:
        #    [from_name, to_name, raa, rab, rac, rbb, rbc, rcc, xaa, xab, xac, xbb, xbc, xcc]
        real_values = (row.raa, row.rab, row.rac, row.rbb, row.rbc, row.rcc)
        imag_values = (row.xaa, row.xab, row.xac, row.xbb, row.xbc, row.xcc)

        for pp, rv, iv in zip(phase_pairs, real_values, imag_values):
            r[pp][(fb, tb)] += rv
            r[pp][(tb, fb)] += rv

            x[pp][(fb, tb)] += iv
            x[pp][(tb, fb)] += iv

    r["ba"] = r["ab"]
    r["ca"] = r["ac"]
    r["cb"] = r["bc"]

    x["ba"] = x["ab"]
    x["ca"] = x["ac"]
    x["cb"] = x["bc"]

    ## parsing gen_data
    if gen is not None:
        gen['name'] = gen['name'].astype(str)
        gen_set = set(gen['name'])
        gen_lookup = gen.set_index('name')

        # Extract phase information for each generator
        gen_phases = {i: list(gen_lookup.at[i, 'phases']) for i in gen_set}

        p_D = {(t, i, ph): gen_lookup.at[i, f"p{ph}"] * pvshape[t] for t in Tset for i in gen_set for ph in gen_phases[i]}
        s_D = {(i, ph): gen_lookup.at[i, f"s{ph}_max"] for i in gen_set for ph in gen_phases[i]}
    else:
        gen_set = []
        gen_phases = {}
        p_D = {}
        s_D = {}


    ## parsing bat_data
    if bat is not None:
        bat['name'] = bat['name'].astype(str)
        bat_set = set(bat['name'])
        bat_lookup = bat.set_index('name')

        # Extract phase information for each battery
        bat_phases = {i: list(bat_lookup.at[i, 'phases']) for i in bat_set}
        p_B = {(i): sum(bat_lookup.at[i, f"Pb_max_{ph}"] for ph in bat_phases[i]) for i in bat_set}
        s_B = {(i): sum(bat_lookup.at[i, f"hmax_{ph}"] for ph in bat_phases[i]) for i in bat_set}
        eta_c = {(i, ph): bat_lookup.at[i, f"nc_{ph}"] for i in bat_set for ph in bat_phases[i]}
        eta_d = {(i, ph): bat_lookup.at[i, f"nd_{ph}"] for i in bat_set for ph in bat_phases[i]}
        bmin = {(i): sum(bat_lookup.at[i, f"bmin_{ph}"] for ph in bat_phases[i]) for i in bat_set}
        bmax = {(i): sum(bat_lookup.at[i, f"bmax_{ph}"] for ph in bat_phases[i]) for i in bat_set}
        b0 = {(i): (bmin[(i)] + bmax[(i)])/2 for i in bat_set}
        b_R = {(i): bmax[(i)]/0.95 for i in bat_set }
    else:
        bat_set = []
        bat_phases = {}
        p_B = {}
        s_B = {}
        eta_c = {}
        eta_d = {}
        bmin = {}
        bmax = {}
        b0 = {}
        b_R = {}

    data = {
        "Nset": bus_set,
        "Lset": branch_set,
        "Dset": gen_set,
        "Bset": bat_set,
        'substationBus': substationBus,
        'T': T,
        'Tset': Tset,
        'phases': phases,
        'bus_phases': bus_phases,
        'branch_phases': branch_phases,
        'gen_phases': gen_phases,
        'bat_phases': bat_phases,
        'r': r,
        'x': x,
        'p_L': p_L,
        'q_L': q_L,
        'v_min': v_min,
        'v_max': v_max,
        'v_swing': v_swing,
        'p_D': p_D,
        's_D': s_D,
        'eta_c': eta_c,
        'eta_d': eta_d,
        'bmin': bmin,
        'bmax': bmax,
        'p_B': p_B,
        's_B': s_B,
        'loadshape': loadshape,
        'pvshape': pvshape,
        'b0': b0,
        'b_R': b_R,
        'costshape': costshape,
        'bfs_nodes': bfs_nodes,
        'bfs_edges': bfs_edges
    }
    return data
