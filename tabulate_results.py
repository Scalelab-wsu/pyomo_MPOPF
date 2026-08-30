"""
Read saved DDDP-OTD pkl files and print a compact table:
  System | P | iters | obj (UB, $/day) | gap% | total time (s)
"""
import os
import pickle

run_logs = os.path.join(os.path.dirname(__file__), 'run_logs')
partitions = [1, 2, 3, 4, 6, 8, 12]
systems    = ['IEEE_123', 'IEEE_9500']
model_tag  = 'linear_new'   # change to 'linear' for LP results

rows = []
for sys in systems:
    for P in partitions:
        path = os.path.join(run_logs, f'dddp_{sys}_P{P}_{model_tag}.pkl')
        if not os.path.exists(path):
            continue

        with open(path, 'rb') as f:
            d = pickle.load(f)

        ub      = d['ub_history'][-1] if d['ub_history'] else float('nan')
        lb      = d['lb_history'][-1] if d['lb_history'] else float('nan')
        gap_pct = 100.0 * d['gap_rel_history'][-1] if d['gap_rel_history'] else float('nan')
        iters   = d['n_iters']
        t_total = d['total_s']
        conv    = 'Y' if d.get('converged', False) else 'N'

        rows.append((sys, P, conv, iters, lb, ub, gap_pct, t_total))

# ── Print DDDP-OTD table ─────────────────────────────────────────────────────
hdr = f"{'System':<14} {'P':>3} {'Conv':>5} {'Iters':>6} {'LB ($/day)':>13} {'UB ($/day)':>13} {'Gap%':>7} {'Time (s)':>9}"
sep = '-' * len(hdr)
print(f"\nDDDP-OTD partition sweep — {model_tag.upper()} model")
print(sep)
print(hdr)
print(sep)
for sys, P, conv, iters, lb, ub, gap_pct, t in rows:
    print(f"{sys:<14} {P:>3} {conv:>5} {iters:>6} {lb:>13.2f} {ub:>13.2f} {gap_pct:>7.3f} {t:>9.1f}")
print(sep)

# ── Temporal ADMM table ───────────────────────────────────────────────────────
# tadmm files use 'isocp'/'linear' without the '_new' suffix
tadmm_tag = model_tag.replace('_new', '')
tadmm_rows = []
for sys in systems:
    for P in partitions:
        path = os.path.join(run_logs, f'tadmm_{sys}_P{P}_{tadmm_tag}.pkl')
        if not os.path.exists(path):
            continue

        with open(path, 'rb') as f:
            d = pickle.load(f)

        cost    = float(d['total_cost']) if d.get('total_cost') is not None else float('nan')
        prim    = float(d['prim_hist'][-1]) if d.get('prim_hist') else float('nan')
        dual    = float(d['dual_hist'][-1]) if d.get('dual_hist') else float('nan')
        iters   = d['n_iters']
        t_total = d['total_s']
        conv    = 'Y' if d.get('converged', False) else 'N'

        tadmm_rows.append((sys, P, conv, iters, cost, prim, dual, t_total))

hdr2 = f"{'System':<14} {'P':>3} {'Conv':>5} {'Iters':>6} {'Cost ($/day)':>13} {'Prim res':>10} {'Dual res':>10} {'Time (s)':>9}"
sep2 = '-' * len(hdr2)
print(f"\nTemporal ADMM partition sweep — {tadmm_tag.upper()} model")
print(sep2)
print(hdr2)
print(sep2)
for sys, P, conv, iters, cost, prim, dual, t in tadmm_rows:
    print(f"{sys:<14} {P:>3} {conv:>5} {iters:>6} {cost:>13.2f} {prim:>10.4e} {dual:>10.4e} {t:>9.1f}")
print(sep2)

# ── OTD-Schwarz table ─────────────────────────────────────────────────────────
otd_tag  = model_tag.replace('_new', '')
otd_rows = []
for sys in systems:
    for P in partitions:
        path = os.path.join(run_logs, f'otd_{sys}_P{P}_{otd_tag}.pkl')
        if not os.path.exists(path):
            continue

        with open(path, 'rb') as f:
            d = pickle.load(f)

        obj    = d['obj_history'][-1]  if d.get('obj_history')   else float('nan')
        delta  = d['delta_history'][-1] if d.get('delta_history') else float('nan')
        iters  = d['n_iters']
        t_total = d['total_s']
        conv   = 'Y' if d.get('converged', False) else 'N'

        otd_rows.append((sys, P, conv, iters, obj, delta, t_total))

hdr3 = f"{'System':<14} {'P':>3} {'Conv':>5} {'Iters':>6} {'Obj ($/day)':>13} {'ΔB (final)':>12} {'Time (s)':>9}"
sep3 = '-' * len(hdr3)
print(f"\nOTD-Schwarz partition sweep — {otd_tag.upper()} model")
print(sep3)
print(hdr3)
print(sep3)
for sys, P, conv, iters, obj, delta, t in otd_rows:
    print(f"{sys:<14} {P:>3} {conv:>5} {iters:>6} {obj:>13.2f} {delta:>12.4e} {t:>9.1f}")
print(sep3)
