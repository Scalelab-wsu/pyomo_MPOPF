"""
1-row × 2-col figure: [IEEE 123 | IEEE 9500].
Each subplot combines time (bars, left y-axis) + iterations (lines, right y-axis).
  Bars:  solid = Linear BFM,  hatched = ISOCP  (colored by P)
  Lines: solid = Linear iters, dashed = ISOCP iters
P=1 (COPF) → black. Okabe-Ito palette.
Output: Plot/scalability_combined.pdf
"""
import os, pickle, glob, re
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines  as mlines
import matplotlib.ticker as mticker

RUN_LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_logs')
PLOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Plot')
os.makedirs(PLOT_DIR, exist_ok=True)

_OI         = ['#E69F00','#56B4E9','#009E73','#0072B2','#D55E00','#CC79A7']
_COPF_COLOR = '#000000'

plt.rcParams.update({
    'font.family':'serif','font.serif':['Times New Roman','Times','DejaVu Serif'],
    'mathtext.fontset':'stix','font.size':7.5,'axes.labelsize':7.5,
    'axes.titlesize':8,'legend.fontsize':6.5,'xtick.labelsize':6.5,
    'ytick.labelsize':6.5,'axes.linewidth':0.6,
    'xtick.major.width':0.5,'ytick.major.width':0.5,
    'xtick.major.size':2.5,'ytick.major.size':2.5,
    'xtick.direction':'in','ytick.direction':'in',
    'legend.frameon':True,'legend.edgecolor':'0.75','legend.framealpha':0.92,
    'lines.linewidth':1.2,'lines.markersize':4.5,
})

def load(system):
    out = {}
    for tag in ('linear','isocp'):
        out[tag] = {}
        for path in glob.glob(os.path.join(RUN_LOGS,f'dddp_{system}_P*_{tag}.pkl')):
            m = re.search(r'_P(\d+)_', path)
            if not m: continue
            p = int(m.group(1))
            if p in out[tag] and '_new' in path: continue
            with open(path,'rb') as f: out[tag][p] = pickle.load(f)
    return out

d123  = load('IEEE_123')
d9500 = load('IEEE_9500')

parts     = sorted(set(p for d in (d123,d9500) for t in ('linear','isocp') for p in d[t]))
parts_no1 = [p for p in parts if p != 1]

def pcolor(p):
    return _COPF_COLOR if p==1 else _OI[parts_no1.index(p)%len(_OI)]

colors = [pcolor(p) for p in parts]
n  = len(parts)
BW = 0.30
GW = 0.04   # inner gap between the two bars in each P-group
GP = 0.22   # gap between P-groups

x_grp = np.arange(n) * (2*BW + GW + GP)
x_lin = x_grp - BW/2 - GW/2
x_iso = x_grp + BW/2 + GW/2

SYSTEMS = [
    (d123,  'IEEE 123-bus',  1.0,  's'),
    (d9500, 'IEEE 9500-bus', 1/60, 'min'),
]

fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.0),
    gridspec_kw=dict(left=0.08, right=0.96, top=0.78, bottom=0.12, wspace=0.42))

for ax, (d, title, sc, unit) in zip(axes, SYSTEMS):
    ax2 = ax.twinx()   # right axis for iterations

    vlin_t = np.array([d['linear'].get(p,{}).get('total_s',np.nan)*sc for p in parts])
    viso_t = np.array([d['isocp'].get(p,{}).get('total_s',np.nan)*sc  for p in parts])
    vlin_i = np.array([d['linear'].get(p,{}).get('n_iters',np.nan)    for p in parts])
    viso_i = np.array([d['isocp'].get(p,{}).get('n_iters',np.nan)     for p in parts])

    tmax = np.nanmax(np.concatenate([vlin_t, viso_t]))

    # ── Bars: time (left axis) ────────────────────────────────────────────────
    for k, (p, cl) in enumerate(zip(parts, colors)):
        if not np.isnan(vlin_t[k]):
            ax.bar(x_lin[k], vlin_t[k], width=BW, color=cl,
                   edgecolor='#222', lw=0.35, alpha=0.90, zorder=3)
        if not np.isnan(viso_t[k]):
            ax.bar(x_iso[k], viso_t[k], width=BW, color=cl,
                   edgecolor='#222', lw=0.35, alpha=0.50, hatch='/////', zorder=3)

    ax.set_xlim(x_lin[0]-BW*1.0, x_iso[-1]+BW*1.0)
    ax.set_ylim(0, tmax*1.28)
    ax.set_xticks(x_grp)
    ax.set_xticklabels([str(p) for p in parts])
    ax.set_xlabel('Partition $P$', labelpad=2)
    ax.set_ylabel(f'Total time ({unit})', labelpad=3)
    ax.set_title(title, fontsize=8, fontweight='bold', pad=4)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
    ax.grid(axis='y', ls='--', lw=0.28, alpha=0.45, zorder=0)
    ax.spines['top'].set_visible(False)

    # ── Lines: iterations (right axis) ───────────────────────────────────────
    valid = ~np.isnan(vlin_i)
    ax2.plot(x_grp[valid], vlin_i[valid], color='#333333',
             ls='-', marker='o', markersize=4, lw=1.2, zorder=5,
             label='Linear iters')
    valid2 = ~np.isnan(viso_i)
    ax2.plot(x_grp[valid2], viso_i[valid2], color='#333333',
             ls='--', marker='s', markersize=4, lw=1.2, zorder=5,
             label='ISOCP iters')
    ax2.set_ylim(0, np.nanmax(np.concatenate([vlin_i, viso_i]))*1.55)
    ax2.set_ylabel('Benders iterations', labelpad=3)
    ax2.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=5))
    ax2.spines['top'].set_visible(False)

# ── Legend ────────────────────────────────────────────────────────────────────
p_handles = [
    mpatches.Patch(facecolor=pcolor(p), edgecolor='#222', lw=0.35, alpha=0.90,
                   label=f'P={p} (COPF)' if p==1 else f'P={p}')
    for p in parts
]
method_bar = [
    mpatches.Patch(facecolor='#888', edgecolor='#222', lw=0.35,
                   alpha=0.90, label='Linear BFM (bars, solid)'),
    mpatches.Patch(facecolor='#888', edgecolor='#222', lw=0.35,
                   alpha=0.50, hatch='/////', label='ISOCP (bars, hatched)'),
]
method_line = [
    mlines.Line2D([],[], color='#333', ls='-',  marker='o', ms=4, lw=1.2,
                  label='Linear BFM (iters)'),
    mlines.Line2D([],[], color='#333', ls='--', marker='s', ms=4, lw=1.2,
                  label='ISOCP (iters)'),
]
fig.legend(handles=p_handles + method_bar + method_line,
           loc='upper center', bbox_to_anchor=(0.52, 1.01),
           ncol=6, fontsize=6.0, handlelength=1.3,
           borderpad=0.3, columnspacing=0.6, handletextpad=0.35,
           framealpha=0.92, edgecolor='0.75')

for ext, dpi in [('.pdf',600),('.png',200)]:
    out = os.path.join(PLOT_DIR,f'scalability_combined{ext}')
    fig.savefig(out, dpi=dpi, bbox_inches='tight')
    print('Saved ->', out)
