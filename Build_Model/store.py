from pyomo.environ import *
import numpy as np

def store_results(model):
    modelVals = {}
    pu_to_kw = 1

    # Initialize containers for each variable
    modelVals['P_subs'] = {}
    modelVals['Q_subs'] = {}
    modelVals['P'] = {}
    modelVals['Q'] = {}
    modelVals['v'] = {}
    modelVals['p_D'] = {}
    modelVals['q_D'] = {}
    if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
        modelVals['P_c'] = {}
        modelVals['P_d'] = {}
    elif hasattr(model, 'P_b'):
        modelVals['P_b'] = {}
    modelVals['B'] = {}

    # Store the optimization results for each variable
    for t in model.Tset:
        for idx in model.substation_phase_set:
            j, ph = idx
            modelVals['P_subs'][t, ph] = value(model.P_subs[t, j, ph] * pu_to_kw)
            modelVals['Q_subs'][t, ph] = value(model.Q_subs[t, j, ph] * pu_to_kw)

    for t in model.Tset:
        for idx in model.branch_phase_set:
            i, j, ph = idx
            modelVals['P'][t, i, j, ph] = value(model.P[t, i, j, ph] * pu_to_kw)
            modelVals['Q'][t, i, j, ph] = value(model.Q[t, i, j, ph] * pu_to_kw)

    for t in model.Tset:
        for idx in model.bus_phase_set:
            j, ph = idx
            modelVals['v'][t, j, ph] = value(model.v[t, j, ph])

    for t in model.Tset:
        for idx in model.gen_phase_set:
            j, ph = idx
            modelVals['p_D'][t, j, ph] = value(model.p_D[t, j, ph] * pu_to_kw)
            modelVals['q_D'][t, j, ph] = value(model.q_D[t, j, ph] * pu_to_kw)

    # Handle battery variables - check which model type we have
    for t in model.Tset:
        for j in model.Bset:
            if hasattr(model, 'P_c') and hasattr(model, 'P_d'):
                # Linear model with separate charge/discharge
                modelVals['P_c'][t, j] = value(model.P_c[t, j] * pu_to_kw)
                modelVals['P_d'][t, j] = value(model.P_d[t, j] * pu_to_kw)
            elif hasattr(model, 'P_b'):
                # Non-linear model with combined battery power
                modelVals['P_b'][t, j] = value(model.P_b[t, j] * pu_to_kw)
            modelVals['B'][t, j] = value(model.B[t, j])

    modelVals['objective_value'] = value(model.obj)

    return modelVals
