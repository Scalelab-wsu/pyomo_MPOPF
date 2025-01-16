# data_parser.py
import pandas as pd
import os
from scipy.sparse import csr_matrix
import numpy as np

def parse_all_data(bus, branch, gen, bat, loadshape, pvshape, price):
    bus_set = sorted(set(bus['id']))  # Directly convert column to set
    gen_set = sorted(set(gen['id']))
    bat_set = sorted(set(bat['id']))
    branch_set = sorted(set(zip(branch['fb'], branch['tb'])))
    substationBus = list(set(branch['fb']) - set(branch['tb']))
    T = len(loadshape)
    Tset = np.arange(1, T + 1)
    phases = ['a', 'b', 'c']

    ## parsing profiles_data
    loadshape_dict = dict(zip(loadshape['time'], loadshape['M']))
    pvshape_dict = dict(zip(pvshape['time'], pvshape['PV']))
    loadshape = {t: loadshape_dict[t] for t in Tset}
    pvshape = {t: pvshape_dict[t] for t in Tset}
    costshape = {t : price[t-1] for t in Tset}

    ## parsing bus_data
    bus_lookup = bus.set_index('id')
    # p_L = {(i, ph): bus_lookup.at[i, f"pl_{ph}"] for i in bus_set for ph in phases}
    p_L = {(t, i, ph): bus_lookup.at[i, f"pl_{ph}"] * loadshape[t] for t in Tset for i in bus_set for ph in phases}
    q_L = {(t, i, ph): bus_lookup.at[i, f"ql_{ph}"] for t in Tset for i in bus_set for ph in phases}
    v_min = {i: bus_lookup.at[i, "v_min"] for i in bus_set}
    v_max = {i: bus_lookup.at[i, "v_max"] for i in bus_set}
    v_swing = {(t,i,ph): bus_lookup.at[i, f"v_{ph}"] for t in Tset for i in substationBus for ph in phases}

    ## parsing branch_data
    row = np.array(np.r_[branch.fb, branch.tb])
    col = np.array(np.r_[branch.tb, branch.fb])
    r = {
        "aa": csr_matrix((np.r_[branch.raa, branch.raa], (row, col))),
        "ab": csr_matrix((np.r_[branch.rab, branch.rab], (row, col))),
        "ac": csr_matrix((np.r_[branch.rac, branch.rac], (row, col))),
        "bb": csr_matrix((np.r_[branch.rbb, branch.rbb], (row, col))),
        "bc": csr_matrix((np.r_[branch.rbc, branch.rbc], (row, col))),
        "cc": csr_matrix((np.r_[branch.rcc, branch.rcc], (row, col))),
    }
    x = {
        "aa": csr_matrix((np.r_[branch.xaa, branch.xaa], (row, col))),
        "ab": csr_matrix((np.r_[branch.xab, branch.xab], (row, col))),
        "ac": csr_matrix((np.r_[branch.xac, branch.xac], (row, col))),
        "bb": csr_matrix((np.r_[branch.xbb, branch.xbb], (row, col))),
        "bc": csr_matrix((np.r_[branch.xbc, branch.xbc], (row, col))),
        "cc": csr_matrix((np.r_[branch.xcc, branch.xcc], (row, col))),
    }

    ## parsing gen_data
    gen_lookup = gen.set_index('id')
    # p_D = {(i, ph): gen_lookup.at[i, f"p{ph}"] for i in gen_set for ph in phases}
    p_D = {(t, i, ph): gen_lookup.at[i, f"p{ph}"] * pvshape[t] for t in Tset for i in gen_set for ph in phases}

    s_D = {(i, ph): gen_lookup.at[i, f"s{ph}_max"] for i in gen_set for ph in phases}


    ## parsing bat_data
    bat_lookup = bat.set_index('id')
    p_B = {(i, ph): bat_lookup.at[i, f"Pb_max_{ph}"] for i in bat_set for ph in phases}
    s_B = {(i, ph): bat_lookup.at[i, f"hmax_{ph}"] for i in bat_set for ph in phases}
    eta_c = {(i, ph): bat_lookup.at[i, f"nc_{ph}"] for i in bat_set for ph in phases}
    eta_d = {(i, ph): bat_lookup.at[i, f"nd_{ph}"] for i in bat_set for ph in phases}
    bmin = {(i, ph): bat_lookup.at[i, f"bmin_{ph}"] for i in bat_set for ph in phases}
    bmax = {(i, ph): bat_lookup.at[i, f"bmax_{ph}"] for i in bat_set for ph in phases}
    b0 = {(i, ph): bmin[(i, ph)]  for i in bat_set for ph in phases}


    data = {
        "Nset": bus_set,
        "Lset": branch_set,
        "Dset": gen_set,
        "Bset": bat_set,
        'substationBus': substationBus,
        'T': T,
        'Tset': Tset,
        'phases': phases,
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
        'costshape': costshape
    }
    return data
