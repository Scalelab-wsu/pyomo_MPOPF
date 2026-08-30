import plotly.express as px
import plotly.graph_objects as go
import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import itertools


def generate_dynamic_maps(scenarios):
    # Define a list of distinctive colors and marker symbols
    distinct_colors = ["red", "blue", "green", "black", "orange", "purple", "brown", "cyan"]
    marker_symbols = ["x", "circle", "triangle-down", "diamond", "cross", "circle", "triangle-down"]

    # For line dash, we want all lines solid.
    line_dash_map_dynamic = {scenario: "solid" for scenario in scenarios}
    color_map_dynamic = {scenario: color for scenario, color in zip(scenarios, itertools.cycle(distinct_colors))}
    symbol_map_dynamic = {scenario: symbol for scenario, symbol in zip(scenarios, itertools.cycle(marker_symbols))}

    return color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic


###############################################################################
# Helper Functions
###############################################################################
def save_plot(fig, filename, width=700, height=400):
    """
    Save the figure (HTML) to the same directory as this script.
    """
    fig.update_layout(
        width=width,  # px width for the figure
        height=height,  # px height for the figure
        # margin=dict(l=0.1, r=0.1, t=0.1, b=0.1)
    )
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    fig.write_html(filepath)

def save_png(fig, filename, width=3.5, height=2.5, dpi=400):
    """
    Save the figure (PNG or other formats) to the same directory as this script.

    Parameters:
    fig: Matplotlib figure to save.
    filename: Filename to save the figure.
    """
    fig.set_size_inches(width, height)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    fig.savefig(filepath, dpi=dpi,format='pdf',bbox_inches='tight')

###############################################################################
# 1) plot_substation_power
###############################################################################
def plot_substation_power(**modelVals_list):
    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, phase), val in mv["P_subs"].items():
            data.append({
                "time": time,
                "phase": f"phase={phase}",
                "scenario": scenario_label,
                "value": val
            })

    fig = px.bar(
        pd.DataFrame(data),
        x="time", y="value",
        color="scenario", pattern_shape="scenario" if len(modelVals_list) > 1 else None,
        facet_col="phase",
        title="Substation Power" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        barmode="group"
    )
    fig.update_traces(marker_line_width=0, marker_line_color='black')
    fig.update_traces(marker_pattern_fillmode='overlay')
    save_plot(fig, "P_subs.html")
    fig.show()


###############################################################################
# 2) plot_battery_soc
###############################################################################
def plot_battery_soc(**modelVals_list):
    """
    Usage:
      plot_battery_soc(modelvals)
      plot_battery_soc(modelvals, OpendssVals, ...)
    Expects:
      modelVals["B"] : dict with (time, node, phase) -> value
    """

    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node), val in mv["B"].items():
            data.append({
                "time": time,
                "node": node,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node"] = df["node"]
    # Sort by numeric node number
    df = df.sort_values(by=["time", "node","scenario"])

    fig = px.bar(
        df,
        x="time", y="value",
        color="scenario", pattern_shape="node" ,
        title="Battery State of Charge" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        barmode="group"
    )
    fig.update_traces(marker_line_width=0, marker_line_color='black')
    fig.update_traces(marker_pattern_fillmode='overlay')
    save_plot(fig, "battery_soc.html")
    fig.show()


###############################################################################
# 3) plot_reactive_power_flows
###############################################################################
def plot_reactive_power_flows(**modelVals_list):
    """
    Usage:
      plot_reactive_power_flows(modelvals, OpendssVals, ...)
    Expects:
      modelVals["Q"] : dict with (time, (fb,tb), phase) -> value
    """

    data = []

    common_q_keys = set.intersection(*[set(mv["Q"].keys()) for mv in modelVals_list.values()])
    common_q_keys = sorted(common_q_keys, key=lambda x: (x[0], x[1][1]))
    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for key in common_q_keys:
            time, fb, tb, phase = key
            val = mv['Q'][key]
            data.append({
                "time": time,
                "branch": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    df[["fb", "tb"]] = df["branch"].str.split("->", expand=True)
    df["fb"] = df["fb"]
    df["tb"] = df["tb"]
    df = df.sort_values(by=["time", "tb","phase","scenario"]).reset_index(drop=True)
    df["branch_label"] = df.apply(lambda row: f"{row['fb']}->{row['tb']}", axis=1)
    branch_order = df["branch_label"].unique().tolist()
    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)
    fig = px.line(
        df,
        x="time", y="value",
        color="scenario",
        symbol = "scenario",
        line_dash="branch_label" if len(modelVals_list) > 1 else None,
        facet_col="phase",
        title="Reactive Power Flows" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        line_dash_map=line_dash_map_dynamic,  # Use custom marker symbols
        category_orders={"branch_label": branch_order},
        markers = True
    )
    fig.update_traces(
        marker=dict(size=4),
        line=dict(width=2)  # bigger marker # thicker line
    )

    save_plot(fig, "reactive_power_flows.html")
    fig.show()


###############################################################################
# 4) plot_der_reactive_power
###############################################################################
def plot_der_reactive_power(**modelVals_list):
    """
    Usage:
      plot_der_reactive_power(modelvals, OpendssVals, ...)
    Expects:
      modelVals["q_D"] : dict with (time, node, phase) -> value
    """

    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase), val in mv["q_D"].items():
            data.append({
                "time": time,
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node"] = df["node"].astype(int)
    # Sort by numeric node number
    df = df.sort_values(by=["time", "node","phase","scenario"])

    fig = px.bar(
        df,
        x="time", y="value",
        color="scenario", facet_col="phase", pattern_shape="node" if len(modelVals_list) > 1 else None,
        title="DER Reactive Power" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        barmode="group"
    )
    fig.update_traces(marker_line_width=0, marker_line_color='black')
    fig.update_traces(marker_pattern_fillmode='overlay')
    save_plot(fig, "DER_reactive_power.html")
    fig.show()


###############################################################################
# 5) plot_battery_charging_discharging_combined
###############################################################################
def plot_battery_charging_discharging_combined(**modelVals_list):
    """
    Usage:
      plot_battery_charging_discharging_combined(modelvals, OpendssVals, ...)

    Expects:
      modelVals["P_c"]: (time, node, phase) -> value (charging)
      modelVals["P_d"]: (time, node, phase) -> value (discharging)
    We'll store charging as negative, discharging as positive.
    """

    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase), val in mv["P_c"].items():
            data.append({
                "time": time,
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": -val,   # Negative for charging
                "type": "Charging"
            })
        for (time, node, phase), val in mv["P_d"].items():
            data.append({
                "time": time,
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val,    # Positive for discharging
                "type": "Discharging"
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node"] = df["node"].astype(int)
    # Sort by numeric node number
    # If time is already numeric:
    df = df.sort_values(by=["time", "node","phase","scenario"])

    fig = px.bar(
        df,
        x="time", y="value",
        color="scenario",
        facet_col="phase",
        pattern_shape="node" if len(modelVals_list) > 1 else None,
        title="Battery Charging & Discharging" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        barmode="group"
    )
    fig.update_traces(marker_line_width=0, marker_line_color='black')
    fig.update_traces(marker_pattern_fillmode='overlay')
    save_plot(fig, "Battery_Charging_Discharging_Combined.html")
    fig.show()


###############################################################################
# 6) plot_active_power_flows
###############################################################################
def plot_active_power_flows(**modelVals_list):
    """
    Usage:
      plot_active_power_flows(modelvals, OpendssVals, ...)
    Expects:
      modelVals["P"] : dict with (time, (fb, tb), phase) -> value
    """

    data = []

    common_p_keys = set.intersection(*[set(mv["P"].keys()) for mv in modelVals_list.values()])
    common_p_keys = sorted(common_p_keys, key=lambda x: (x[0], x[1][1]))
    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for key in common_p_keys:
            time, fb, tb, phase = key
            val = mv['P'][key]
            data.append({
                "time": time,
                "branch": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    df[["fb", "tb"]] = df["branch"].str.split("->", expand=True)
    df["fb"] = df["fb"]
    df["tb"] = df["tb"]
    df = df.sort_values(by=["time", "tb","phase","scenario"]).reset_index(drop=True)
    df["branch_label"] = df.apply(lambda row: f"{row['fb']}->{row['tb']}", axis=1)
    branch_order = df["branch_label"].unique().tolist()
    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)
    fig = px.line(
        df,
        x="time", y="value",
        color="scenario", line_dash="branch_label" if len(modelVals_list) > 1 else None,
        facet_col="phase",
        title="Active Power Flows" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        line_dash_map=line_dash_map_dynamic, # Use custom marker symbols
        category_orders={"branch_label": branch_order},
        markers=True
    )
    fig.update_traces(
        marker=dict(size=3),
        line=dict(width=1)  # bigger marker # thicker line
    )
    save_plot(fig, "active_power_flows.html")
    fig.show()


###############################################################################
# 7) plot_voltage
###############################################################################
def plot_voltage(**modelVals_list):
    """
    Usage:
      plot_voltage(modelvals, OpendssVals, ...)
    Expects:
      modelVals["v"] : dict with (time, node, phase) -> value
    """

    data = []

    common_v_keys = set.intersection(*[set(mv["v"].keys()) for mv in modelVals_list.values()])
    for scenario_name,mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for key in common_v_keys:
            time, node, phase = key
            val = mv["v"][key]
            data.append({
                "time": time,
                "node": node,  # e.g. "node=13"
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })

    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node"] = df["node"].astype(int)
    # Sort by numeric node number
    # If time is already numeric:
    df = df.sort_values(by=["time", "node","phase","scenario"])

    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)

    fig = px.line(
        df,
        # df[df["time"] == "t=5"], ## employ this for just one time plotting to remove mess
        x="time",     # use the numeric column on the x-axis
        y="value",
        color="scenario",
        line_dash="node",
        symbol="scenario" if len(modelVals_list) > 1 else None,
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        # line_dash_map=line_dash_map_dynamic,  # Use custom marker symbols
        labels={"value": "Voltage (pu)"},
        category_orders={"phase": ["a", "b", "c"],"scenario":["copf","admm","enapp"]},
        facet_row="phase",
        # title="Voltage for Nodes" + (" (All Scenarios)" if len(modelVals_list) > 1 else ""),
        markers = True
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 20, "t": 25, "b": 10},
        xaxis_title="nodes",
        yaxis_title="Voltage (pu)" ,
        font_color="black",
        legend_xref = "paper",
        legend_title_text="",
        legend_orientation="v",
        legend_borderwidth=1,
        yaxis_matches="y",
        # legend_x=0.95,
        # legend_y=-0.2,
        # yaxis_title_standoff = 0.0,
    )
    fig.update_layout(
        legend=dict(
            x=1.02,  # Horizontal position of legend within the plot (0=left, 1=right)
            y=1,  # Vertical position (0=bottom, 1=top)
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.5)",  # A semi-transparent legend box
        )
    )
    fig.update_layout(font=dict(size=12, family="Times New Roman"))

    fig.update_traces(
        marker=dict(size=4),
        line=dict(width=1)# bigger marker # thicker line
    )
    save_plot(fig, "voltage_plot.pdf")
    fig.show()

def plot_convergence(*args):
    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 6))

    for i, convergence in enumerate(args):
        xvalues = list(convergence.keys())
        con = list(convergence.values())
        ax.plot(xvalues, con, label=f'Convergence Trend {i + 1}')

    ax.set_xlabel('No. of Iterations')
    ax.set_ylabel('Convergence Tolerance')
    ax.set_title('Convergence vs No. of Iterations')
    ax.legend()
    ax.set_yscale('log')

    # Save the figure as PNG
    save_png(fig, "convergence.png")

    # Show the plot
    plt.show()

def plot_objective(*args):
    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 6))

    for i, objective in enumerate(args):
        xvalues = list(objective.keys())
        con = list(objective.values())
        ax.plot(xvalues, con, label=f'Objective Trend {i + 1}')

    ax.set_xlabel('No. of Iterations')
    ax.set_ylabel('Objective Value')
    ax.set_title('Objective value vs No. of Iterations')
    ax.legend()

    # Save the figure as PNG
    save_png(fig, "objective.png")

    # Show the plot
    plt.show()

def plot_input_profiles(**profiles_dict):
    fig, ax = plt.subplots(figsize=(10, 6))

    for name, profiles in profiles_dict.items():
        xvalues = list(profiles.keys())
        con = list(profiles.values())
        ax.plot(xvalues, con, label=name)
    ax.legend(loc='upper left')
    ax.set_xlabel('Time (h)')
    ax.set_ylabel('Multipliers')
    # ax.set_title('Convergence vs No. of Iterations')
    ax.legend()

    save_png(fig, "input_profiles.pdf")
    plt.show()

def plot_convergence_comparison(**solution_dict):
    color_palette = {
        "copf":  "black",
        "dddp":  "#d62728",
        "enapp": "#1f77b4",
        "admm":  "#2ca02c",
    }
    fallback_colors = ["orange", "purple", "brown", "cyan"]

    fig = go.Figure()
    max_iter = 1
    copf_trace = None  # sentinel

    for scenario_name, sol in solution_dict.items():
        label = scenario_name.replace("Vals", "").upper()
        key   = scenario_name.replace("Vals", "").lower()
        color = color_palette.get(key, fallback_colors[len(fig.data) % len(fallback_colors)])

        if key == "copf":
            ef_obj = sol.get("objective_value")
            if ef_obj is not None:
                copf_trace = (ef_obj, label, color)  # store, draw after loop

        elif key == "dddp":
            lb = sol.get("LB", [])
            ub = sol.get("UB", [])
            if lb:
                iters = list(range(1, len(lb) + 1))
                max_iter = max(max_iter, len(lb))
                fig.add_trace(go.Scatter(
                    x=iters, y=lb,
                    mode="lines+markers",
                    name=f"{label} – Lower Bound",
                    line=dict(color=color, width=2),
                    marker=dict(size=6, symbol="square")
                ))
            if ub:
                iters = list(range(1, len(ub) + 1))
                max_iter = max(max_iter, len(ub))
                fig.add_trace(go.Scatter(
                    x=iters, y=ub,
                    mode="lines+markers",
                    name=f"{label} – Upper Bound",
                    line=dict(color=color, width=2, dash="dash"),
                    marker=dict(size=6, symbol="square-open")
                ))

        else:
            values = sol.get("values", [])
            if isinstance(values, dict):
                values = list(values.values())
            if values:
                iters = list(range(1, len(values) + 1))
                max_iter = max(max_iter, len(values))
                fig.add_trace(go.Scatter(
                    x=iters, y=values,
                    mode="lines+markers",
                    name=label,
                    line=dict(color=color, width=2),
                    marker=dict(size=6, symbol="circle")
                ))

    # Draw COPF horizontal line now that max_iter is known
    if copf_trace is not None:
        ef_obj, label, color = copf_trace
        fig.add_trace(go.Scatter(
            x=[1, max_iter], y=[ef_obj, ef_obj],
            mode="lines",
            name=f"{label} (Exact)",
            line=dict(color=color, width=3, dash="dot")
        ))

    fig.update_layout(
        title=dict(
            text="<b>Convergence Comparison</b>",
            x=0.5, xanchor="center",
            font=dict(size=18, family="Times New Roman")
        ),
        xaxis=dict(title="<b>Iteration</b>", showgrid=True, gridcolor="lightgray"),
        yaxis=dict(title="<b>Objective Value</b>", showgrid=True, gridcolor="lightgray"),
        plot_bgcolor="white",
        font=dict(size=13, family="Times New Roman", color="black"),
        legend=dict(
            x=1.02, y=1, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="black", borderwidth=1
        ),
        hovermode="x unified",
        height=500, width=800
    )

    save_plot(fig, "convergence_comparison.pdf")
    fig.show()


def plot_isocp_convergence(*series, out_path="isocp_convergence.svg",
                           xlabel="Iteration $m$",
                           ylabel="Max SOCP relaxation error (p.u.)",
                           figsize=(3.5, 2.4), floor=1e-16, log_scale=True):
    """Plot max ISOCP conic gap vs iteration for one or more systems.

    Each positional ``series`` argument describes one curve. Accepted forms:
        (label, errors)              -> iters inferred as 0..len(errors)-1
        (label, iters, errors)       -> explicit iteration indices
        {"label": str, "errors": [...], "iters": [...] (optional),
         "marker": str (optional), "color": str (optional),
         "linestyle": str (optional)}

    ``out_path`` may be absolute or relative to this Plotting.py directory.
    The figure is saved as SVG (paper-quality, single-column IEEE width).
    """
    import numpy as np
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        'font.family': 'serif',
        'font.serif': ['Times New Roman', 'Times', 'DejaVu Serif'],
        'mathtext.fontset': 'stix',
        'font.size': 8,
        'axes.labelsize': 8,
        'axes.titlesize': 9,
        'legend.fontsize': 7,
        'xtick.labelsize': 7,
        'ytick.labelsize': 7,
        'axes.linewidth': 0.6,
        'lines.linewidth': 1.1,
        'lines.markersize': 3.2,
        'xtick.major.width': 0.5,
        'ytick.major.width': 0.5,
        'xtick.major.size': 2.5,
        'ytick.major.size': 2.5,
        'legend.frameon': False,
    })

    default_markers = ['o', 's', '^', 'D', 'v', 'P', 'X', '*']
    default_colors = ['#000000', '#1f77b4', '#d62728', '#2ca02c',
                      '#ff7f0e', '#9467bd', '#8c564b', '#17becf']
    default_styles = ['-', '--', ':', '-.']

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    max_iter_seen = 0

    for k, s in enumerate(series):
        if isinstance(s, dict):
            label = s["label"]
            errors = np.asarray(s["errors"], dtype=float)
            iters = np.asarray(s.get("iters", np.arange(len(errors))))
            marker = s.get("marker", default_markers[k % len(default_markers)])
            color = s.get("color", default_colors[k % len(default_colors)])
            linestyle = s.get("linestyle", default_styles[k % len(default_styles)])
        elif len(s) == 2:
            label, errors = s
            errors = np.asarray(errors, dtype=float)
            iters = np.arange(len(errors))
            marker = default_markers[k % len(default_markers)]
            color = default_colors[k % len(default_colors)]
            linestyle = default_styles[k % len(default_styles)]
        elif len(s) == 3:
            label, iters, errors = s
            iters = np.asarray(iters)
            errors = np.asarray(errors, dtype=float)
            marker = default_markers[k % len(default_markers)]
            color = default_colors[k % len(default_colors)]
            linestyle = default_styles[k % len(default_styles)]
        else:
            raise ValueError(f"Unsupported series form: {s!r}")

        y = np.maximum(errors, floor) if log_scale else errors
        plot_fn = ax.semilogy if log_scale else ax.plot
        plot_fn(iters, y, marker=marker, linestyle=linestyle,
                color=color, label=label, zorder=3)
        if len(iters):
            max_iter_seen = max(max_iter_seen, int(np.max(iters)))

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xlim(left=-0.4, right=max_iter_seen + 0.4)
    ax.set_xticks(np.arange(0, max_iter_seen + 1))
    ax.grid(True, which='major', linestyle='-', linewidth=0.3, alpha=0.5)
    ax.grid(True, which='minor', linestyle=':', linewidth=0.25, alpha=0.4)
    if series:
        ax.legend(loc='upper right', handlelength=2.0, borderpad=0.3,
                  labelspacing=0.3)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)

    if not os.path.isabs(out_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_path = os.path.join(script_dir, out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fmt = os.path.splitext(out_path)[1].lstrip('.') or 'svg'
    fig.savefig(out_path, format=fmt, bbox_inches='tight', pad_inches=0.02)
    plt.close(fig)
    print(f"saved {out_path}")
    return out_path


def plot_otd_convergence(*series, out_path="otd_convergence.svg",
                          xlabel="OTD iteration $k$",
                          ylabel=r"Max boundary error $\Delta B$ (p.u.)",
                          figsize=(3.5, 2.4), floor=1e-16, log_scale=True):
    """Plot OTD Schwarz boundary error vs iteration for one or more cases.

    Accepts the same variadic series format as plot_isocp_convergence:
        (label, errors)
        (label, iters, errors)
        {"label": ..., "errors": ..., "iters": ..., "marker": ..., ...}

    Use log_scale=False for a linear y-axis.
    """
    return plot_isocp_convergence(*series, out_path=out_path, xlabel=xlabel,
                                   ylabel=ylabel, figsize=figsize,
                                   floor=floor, log_scale=log_scale)


def plot_dddp_otd_convergence(*runs,
                               out_path="dddp_otd_convergence.pdf",
                               tol=1e-3,
                               obj_scale=1000,
                               obj_unit='\$',
                               figsize=(3.5, 4.8)):
    """Publication-quality stacked two-panel convergence figure for DDDP-OTD.

    Single-column IEEE Transactions width (3.5 in), two rows:
      (a) UB / LB objective trajectories — colour = method, marker = UB vs LB
      (b) Relative optimality gap on log scale

    Visual encoding:
      - Colour distinguishes the method  (run 0 = black, run 1 = blue, ...)
      - Solid line + filled marker  = UB
      - Dashed line + open marker   = LB
      - Distinct marker shapes per method (circle, square, triangle, ...)

    Each positional ``run`` is a dict with keys:
        label       str          e.g. "Linear BFM" or "ISOCP"
        lb_history  list[float]  lower bound per iteration
        ub_history  list[float]  upper bound per iteration (length >= lb)
        color       str          line colour (optional)
    """
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    _IEEE_RC = {
        'font.family':       'serif',
        'font.serif':        ['Times New Roman', 'Times', 'DejaVu Serif'],
        'mathtext.fontset':  'stix',
        'font.size':         8,
        'axes.labelsize':    8,
        'axes.titlesize':    8,
        'legend.fontsize':   7,
        'xtick.labelsize':   7,
        'ytick.labelsize':   7,
        'axes.linewidth':    0.6,
        'lines.linewidth':   1.3,
        'lines.markersize':  4.0,
        'xtick.major.width': 0.5,
        'ytick.major.width': 0.5,
        'xtick.major.size':  2.5,
        'ytick.major.size':  2.5,
        'legend.frameon':    True,
        'legend.edgecolor':  '0.8',
        'legend.framealpha': 0.9,
    }
    plt.rcParams.update(_IEEE_RC)

    # One colour and marker shape per run (method)
    _COLORS = ['#000000', '#1f77b4', '#d62728', '#2ca02c', '#ff7f0e']
    _MARKS  = ['o', 's', '^', 'D', 'v']

    fig, (ax_obj, ax_gap) = plt.subplots(
        2, 1, figsize=figsize,
        gridspec_kw={'hspace': 0.12},
        constrained_layout=False,
    )
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.09,
                        hspace=0.16)

    max_iter = 0
    legend_handles = []

    for k, run in enumerate(runs):
        label  = run['label']
        lb     = np.asarray(run['lb_history'], dtype=float)
        ub_raw = np.asarray(run['ub_history'],  dtype=float)
        n      = len(lb)
        ub     = ub_raw[:n]
        iters  = np.arange(1, n + 1)
        color  = run.get('color', _COLORS[k % len(_COLORS)])
        mark   = _MARKS[k % len(_MARKS)]
        max_iter = max(max_iter, n)

        # ── (a) LB only (scaled to actual units) ──────────────────────────
        ax_obj.plot(iters, lb * obj_scale,
                    color=color, linestyle='-', marker=mark,
                    markerfacecolor=color, markeredgecolor=color,
                    linewidth=1.4, markersize=4.5, zorder=4,
                    label=label)

        # ── (b) relative gap (computed on unscaled values) ────────────────
        gap = np.abs(ub - lb) / np.maximum(1.0, np.abs(ub))
        gap = np.maximum(gap, 1e-16)
        ax_gap.semilogy(iters, gap,
                        color=color, linestyle='-', marker=mark,
                        markerfacecolor=color, markeredgecolor=color,
                        linewidth=1.4, markersize=4.5, zorder=4,
                        label=label)

    # Tolerance line on gap panel
    if max_iter > 0:
        ax_gap.axhline(tol, color='#888888', linestyle=':', linewidth=1.0,
                       label=f'Tolerance $\\epsilon={tol:.0e}$', zorder=2)

    # ── Panel (a) cosmetics ───────────────────────────────────────────────────
    ax_obj.set_xlabel('')
    ax_obj.tick_params(labelbottom=False)
    ax_obj.set_ylabel(f'Objective Value (LB)({obj_unit})')
    ax_obj.set_xlim(0.5, max_iter + 0.5)
    ax_obj.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_obj.grid(True, linestyle='--', linewidth=0.3, alpha=0.6)
    ax_obj.spines['top'].set_visible(False)
    ax_obj.spines['right'].set_visible(False)
    ax_obj.legend(loc='lower right', handlelength=1.8,
                  borderpad=0.4, labelspacing=0.25, fontsize=7)

    # ── Panel (b) cosmetics ───────────────────────────────────────────────────
    ax_gap.set_xlabel('Iteration $k$')
    ax_gap.set_ylabel(r'$\frac{|\mathrm{UB} - \mathrm{LB}|}{|\mathrm{UB}|}$')
    ax_gap.set_xlim(0.5, max_iter + 0.5)
    ax_gap.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_gap.yaxis.set_major_locator(mticker.LogLocator(base=10))
    ax_gap.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
    ax_gap.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
    ax_gap.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.4)
    ax_gap.spines['top'].set_visible(False)
    ax_gap.spines['right'].set_visible(False)
    ax_gap.legend(loc='lower left', handlelength=1.8,
                  borderpad=0.4, labelspacing=0.25, fontsize=7)

    # ── Save ─────────────────────────────────────────────────────────────────
    if not os.path.isabs(out_path):
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fmt = os.path.splitext(out_path)[1].lstrip('.') or 'pdf'
    fig.savefig(out_path, format=fmt, bbox_inches='tight', pad_inches=0.02,
                dpi=600)
    plt.close(fig)
    print(f"saved {out_path}")
    return out_path


###############################################################################
# DDDP-OTD partition comparison plots
###############################################################################

# ── shared rcParams and palette ───────────────────────────────────────────────
_IEEE_RC = {
    'font.family':        'serif',
    'font.serif':         ['Times New Roman', 'Times', 'DejaVu Serif'],
    'mathtext.fontset':   'stix',
    'font.size':          8,
    'axes.labelsize':     8,
    'axes.titlesize':     8,
    'legend.fontsize':    7,
    'xtick.labelsize':    7,
    'ytick.labelsize':    7,
    'axes.linewidth':     0.8,
    'lines.linewidth':    1.6,
    'lines.markersize':   5.0,
    'xtick.major.width':  0.8,
    'ytick.major.width':  0.8,
    'xtick.minor.width':  0.5,
    'ytick.minor.width':  0.5,
    'xtick.major.size':   3.5,
    'ytick.major.size':   3.5,
    'xtick.minor.size':   2.0,
    'ytick.minor.size':   2.0,
    'xtick.direction':    'in',
    'ytick.direction':    'in',
    'legend.frameon':     True,
    'legend.edgecolor':   '0.8',
    'legend.framealpha':  0.95,
    'pdf.fonttype':       42,
    'ps.fonttype':        42,
}

# Okabe-Ito colorblind-safe palette
_P_COLORS = ['#E69F00', '#56B4E9', '#009E73', '#0072B2', '#D55E00', '#CC79A7']
# Distinct shapes: even-index → filled, odd-index → hollow (set below in loop)
_P_MARKS  = ['o', 's', '^', 'D', 'X', 'p']
# Clearly separated dash patterns
_P_LINES  = ['-', (0,(6,2)), '-.', (0,(3,1,1,1)), (0,(1,1)), (0,(6,1,1,1,1,1))]
_COPF_COLOR = '#d62728'
_BAR_COLOR  = '#1f77b4'


def _load_dddp_runs(run_logs_dir, system_name, partition_list=None,
                    model_tag='isocp'):
    """Load DDDP pkl files.  If partition_list is None, auto-discovers all
    dddp_{system_name}_P*_{model_tag}.pkl files in run_logs_dir."""
    import pickle, glob, re
    runs = {}
    if partition_list is None:
        pattern = os.path.join(run_logs_dir,
                               f'dddp_{system_name}_P*_{model_tag}.pkl')
        found   = sorted(glob.glob(pattern))
        partition_list = []
        for path in found:
            m = re.search(r'_P(\d+)_', path)
            if m:
                partition_list.append(int(m.group(1)))
    for p in partition_list:
        path = os.path.join(run_logs_dir,
                            f'dddp_{system_name}_P{p}_{model_tag}.pkl')
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                runs[p] = pickle.load(f)
    return runs


def _savefig_dddp(fig, out_path):
    """Resolve out_path relative to workspace root if not absolute, then save."""
    if not os.path.isabs(out_path):
        # workspace root is two levels up from Plot/Plotting.py
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out_path = os.path.join(root, out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fmt = os.path.splitext(out_path)[1].lstrip('.') or 'pdf'
    fig.savefig(out_path, format=fmt, bbox_inches='tight', pad_inches=0.01,
                dpi=800)
    plt.close(fig)
    print(f"  saved → {out_path}")
    return out_path


def plot_dddp_partition_lb(run_logs_dir, system_name,
                            partition_list=None,
                            model_tag='isocp',
                            out_path='dddp_partition_lb.pdf',
                            tol=1e-3,
                            obj_unit=r'\$',
                            zoom_lo=None,
                            zoom_hi=None):
    """Two-panel convergence figure comparing DDDP-OTD across partitions P.

    Panel (a) — Lower bound vs. Benders iteration.
      Each partition P gets a distinct colour / marker / line-style.
      The converged COPF value (P = 1 pkl if available, otherwise the tightest
      final LB across all runs) is drawn as a horizontal dashed reference.
      A star marker is placed at the last iteration of each run.

    Panel (b) — Relative optimality gap |UB − LB| / |UB| on a log scale.
      A horizontal tolerance line is drawn at ``tol``.

    Parameters
    ----------
    run_logs_dir   : str   path to directory containing the pkl files.
    system_name    : str   e.g. 'IEEE_123'
    partition_list : list  of ints, or None to auto-discover.
    out_path       : str   output file (pdf / png).  Relative → Plot/ folder.
    tol            : float convergence tolerance (for the reference line).
    obj_unit       : str   y-axis unit label.
    """
    import numpy as np
    import matplotlib.ticker as mticker

    plt.rcParams.update(_IEEE_RC)

    runs = _load_dddp_runs(run_logs_dir, system_name, partition_list,
                           model_tag=model_tag)
    if not runs:
        raise FileNotFoundError(f"No DDDP pkl files found in {run_logs_dir}")

    # COPF reference: P=1 final LB (or best converged LB across all runs)
    copf_lb = None
    if 1 in runs:
        copf_lb = float(np.asarray(runs[1]['lb_history'], dtype=float)[-1])
    else:
        finals = [float(np.asarray(d['lb_history'], dtype=float)[-1])
                  for d in runs.values() if d.get('converged', False)]
        if finals:
            copf_lb = max(finals)

    plot_ps = sorted(p for p in runs if p != 1)

    fig, (ax_lb, ax_gap) = plt.subplots(
        2, 1, figsize=(3.5, 4.8),
        gridspec_kw={'hspace': 0.12},
        constrained_layout=False,
    )
    fig.subplots_adjust(left=0.14, right=0.97, top=0.96, bottom=0.09,
                        hspace=0.45)

    max_iter = 0
    for k, p in enumerate(plot_ps):
        d      = runs[p]
        lb     = np.asarray(d['lb_history'], dtype=float)
        ub     = np.asarray(d['ub_history'], dtype=float)[:len(lb)]
        gap    = np.asarray(d['gap_rel_history'], dtype=float)[:len(lb)]
        iters  = np.arange(1, len(lb) + 1)
        color  = _P_COLORS[k % len(_P_COLORS)]
        mark   = _P_MARKS[k % len(_P_MARKS)]
        ls     = _P_LINES[k % len(_P_LINES)]
        label  = f'$P = {p}$'
        max_iter = max(max_iter, len(lb))

        # Alternate filled (even k) / hollow (odd k) for max shape contrast
        mfc = color if k % 2 == 0 else 'none'
        mew = 0.5    if k % 2 == 0 else 1.4

        # ── LB curve ──────────────────────────────────────────────────────────
        ax_lb.plot(iters, lb, color=color, linestyle=ls,
                   marker=mark, markerfacecolor=mfc,
                   markeredgecolor=color, markeredgewidth=mew,
                   linewidth=1.8, markersize=5.5, zorder=4, label=label)
        # convergence star
        ax_lb.plot(iters[-1], lb[-1], marker='*', color=color,
                   markersize=9.5, zorder=5, linestyle='none',
                   markeredgewidth=0.5, markeredgecolor='k')

        # ── gap curve ─────────────────────────────────────────────────────────
        ax_gap.semilogy(iters, np.maximum(gap, 1e-16),
                        color=color, linestyle=ls, marker=mark,
                        markerfacecolor=mfc, markeredgecolor=color,
                        markeredgewidth=mew,
                        linewidth=1.8, markersize=5.5, zorder=4, label=label)

    # P=1 (COPF) horizontal reference on LB panel
    if copf_lb is not None:
        ax_lb.axhline(copf_lb, color='black', linestyle='-',
                      linewidth=2.0, zorder=3, label='$P=1$')

    # ── Zoom inset: full x-axis, explicit or auto y range ────────────────────
    if copf_lb is not None and max_iter > 1:
        copf_ref_k = copf_lb

        if zoom_lo is not None and zoom_hi is not None:
            y_lo, y_hi = zoom_lo, zoom_hi
        else:
            # Tight window: ±0.1 % of the P=1 optimum so the inset shows
            # only the final-approach band (not the full ramp from scratch).
            span_zoom = copf_lb / 1000.0
            y_lo = copf_lb - span_zoom
            y_hi = copf_lb + span_zoom * 0.25

        # [x0, y0, width, height] in axes-fraction coords.
        # Lower-right is data-empty (all curves have climbed past it by the
        # later iterations), so the inset doesn't cover any meaningful content.
        axin = ax_lb.inset_axes([0.41, 0.09, 0.60, 0.40])
        axin.set_facecolor('white')
        for k, p in enumerate(plot_ps):
            lb_p    = np.asarray(runs[p]['lb_history'], dtype=float)
            iters_p = np.arange(1, len(lb_p) + 1)
            color   = _P_COLORS[k % len(_P_COLORS)]
            mark    = _P_MARKS[k % len(_P_MARKS)]
            ls      = _P_LINES[k % len(_P_LINES)]
            i_mfc   = color if k % 2 == 0 else 'none'
            i_mew   = 0.4   if k % 2 == 0 else 1.1
            axin.plot(iters_p, lb_p, color=color, linestyle=ls, marker=mark,
                      markerfacecolor=i_mfc, markeredgecolor=color,
                      markeredgewidth=i_mew,
                      linewidth=1.2, markersize=4.0, zorder=4)
            axin.plot(iters_p[-1], lb_p[-1], marker='*', color=color,
                      markersize=7.0, zorder=5, linestyle='none',
                      markeredgewidth=0.4, markeredgecolor='k')

        axin.axhline(copf_ref_k, color='black', linestyle='-',
                     linewidth=1.4, zorder=3)

        axin.set_xlim(0.5, max_iter + 0.5)
        axin.set_ylim(y_lo, y_hi)
        axin.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))
        axin.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        axin.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
        axin.tick_params(labelsize=6.5, pad=1.5, length=2.0)
        axin.yaxis.tick_right()
        axin.yaxis.set_label_position('right')
        axin.grid(True, linestyle='--', linewidth=0.25, alpha=0.5)
        for spine in axin.spines.values():
            spine.set_linewidth(0.8)

        # Replace indicate_inset_zoom connectors (which cross the main curves)
        # with a subtle grey band on the main panel marking the zoomed y-region.
        ax_lb.axhspan(y_lo, y_hi,
                      facecolor='#999999', alpha=0.12, zorder=0, lw=0)
        ax_lb.annotate('', xy=(0.995, y_hi), xycoords=('axes fraction', 'data'),
                       xytext=(0.995, y_lo), textcoords=('axes fraction', 'data'),
                       arrowprops=dict(arrowstyle='<->', color='#666666',
                                       lw=0.6, mutation_scale=6),
                       zorder=6)

        # P=1 mini-legend centred just above the top edge of the zoom box
        from matplotlib.lines import Line2D as _L2D
        _p1_handle = _L2D([0], [0], color='black', linestyle='-',
                          linewidth=1.0)
        axin.legend([_p1_handle], [r'$P=1$'],
                    loc='lower center',
                    bbox_to_anchor=(0.5, 1.0),
                    bbox_transform=axin.transAxes,
                    fontsize=7, handlelength=1.3,
                    borderpad=0.3, framealpha=0.95,
                    edgecolor='0.75', ncol=1)

    # Tolerance reference on gap panel (line only, no text label)
    ax_gap.axhline(tol, color='#666666', linestyle=':', linewidth=1.5,
                   zorder=2)

    # ── Panel (a) cosmetics ───────────────────────────────────────────────────
    ax_lb.tick_params(labelbottom=False)
    ax_lb.set_ylabel(f'LB ({obj_unit})')
    ax_lb.set_xlim(0.5, max_iter + 0.5)
    ax_lb.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_lb.grid(True, linestyle='--', linewidth=0.3, alpha=0.6)
    ax_lb.spines['top'].set_visible(False)
    ax_lb.spines['right'].set_visible(False)

    # Annotate the P=1 value at the right edge of the main panel
    if copf_lb is not None:
        ax_lb.annotate(f'{copf_lb:.1f}',
                       xy=(1.0, copf_lb), xycoords=('axes fraction', 'data'),
                       xytext=(3, 0), textcoords='offset points',
                       fontsize=6.5, va='center', ha='left',
                       color='black', fontweight='bold', zorder=7,
                       annotation_clip=False)

    # ── Panel (b) cosmetics ───────────────────────────────────────────────────
    ax_gap.set_xlabel('DDDP Iteration $(k)$')
    ax_gap.set_ylabel(
        r'$\dfrac{\mathrm{UB} - \mathrm{LB}}{\mathrm{UB}}$')
    ax_gap.set_xlim(0.5, max_iter + 0.5)
    ax_gap.set_ylim(1e-5, 2)
    ax_gap.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_gap.yaxis.set_major_locator(mticker.LogLocator(base=10))
    ax_gap.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
    ax_gap.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
    ax_gap.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.35)
    ax_gap.spines['top'].set_visible(False)
    ax_gap.spines['right'].set_visible(False)
    ax_gap.tick_params(axis='y', which='both', direction='in')

    # ── Partition legend (P>1) horizontally between the two subplots ──────────
    handles_lb, labels_lb = ax_lb.get_legend_handles_labels()
    p_pairs = [(h, l) for h, l in zip(handles_lb, labels_lb) if l != '$P=1$']
    if p_pairs:
        h_p, l_p = zip(*p_pairs)
        leg = fig.legend(h_p, l_p,
                         loc='center',
                         bbox_to_anchor=(0.57, 0.510),
                         ncol=len(h_p),
                         fontsize=7,
                         handlelength=1.2,
                         borderpad=0.35,
                         labelspacing=0.2,
                         columnspacing=0.3,
                         framealpha=0.95,
                         edgecolor='0.8')
        leg.set_zorder(10)

    # (P=1 legend is placed on the zoom inset above its top-centre edge)

    return _savefig_dddp(fig, out_path)


def _load_otd_runs(run_logs_dir, system_name, partition_list=None,
                   model_tag='linear'):
    """Load OTD-Schwarz pkl files.  Auto-discovers otd_{system_name}_P*_{model_tag}.pkl."""
    import pickle, glob, re
    runs = {}
    if partition_list is None:
        pattern = os.path.join(run_logs_dir,
                               f'otd_{system_name}_P*_{model_tag}.pkl')
        found = sorted(glob.glob(pattern))
        partition_list = []
        for path in found:
            m = re.search(r'_P(\d+)_', path)
            if m:
                partition_list.append(int(m.group(1)))
    for p in partition_list:
        path = os.path.join(run_logs_dir,
                            f'otd_{system_name}_P{p}_{model_tag}.pkl')
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                runs[p] = pickle.load(f)
    return runs


def plot_otd_partition_convergence(run_logs_dir, system_name,
                                   partition_list=None,
                                   model_tag='linear',
                                   out_path='otd_partition_convergence.pdf',
                                   tol=1e-3,
                                   obj_unit=r'\$',
                                   zoom_lo=None,
                                   zoom_hi=None):
    """Two-panel convergence figure comparing OTD-Schwarz across partitions P.

    Panel (a) — Primal objective vs. Schwarz iteration.
      Each partition gets a distinct colour / marker / line-style.
      The P=1 (single-window) final value is drawn as a horizontal reference.

    Panel (b) — max boundary mismatch ΔB vs. iteration on a log scale.
      A horizontal tolerance line is drawn at ``tol``.
    """
    import numpy as np
    import matplotlib.ticker as mticker

    plt.rcParams.update(_IEEE_RC)

    runs = _load_otd_runs(run_logs_dir, system_name, partition_list,
                          model_tag=model_tag)
    if not runs:
        raise FileNotFoundError(f"No OTD pkl files found in {run_logs_dir}")

    copf_obj = None
    if 1 in runs and runs[1].get('obj_history'):
        copf_obj = float(np.asarray(runs[1]['obj_history'], dtype=float)[-1])

    plot_ps = sorted(p for p in runs if p != 1)

    fig, (ax_obj, ax_db) = plt.subplots(
        2, 1, figsize=(3.5, 4.8),
        gridspec_kw={'hspace': 0.12},
        constrained_layout=False,
    )
    fig.subplots_adjust(left=0.14, right=0.97, top=0.96, bottom=0.09,
                        hspace=0.45)

    max_iter = 0
    for k, p in enumerate(plot_ps):
        d      = runs[p]
        obj    = np.asarray(d['obj_history'],   dtype=float)
        delta  = np.asarray(d['delta_history'], dtype=float)[:len(obj)]
        iters  = np.arange(1, len(obj) + 1)
        color  = _P_COLORS[k % len(_P_COLORS)]
        mark   = _P_MARKS[k % len(_P_MARKS)]
        ls     = _P_LINES[k % len(_P_LINES)]
        label  = f'$P = {p}$'
        max_iter = max(max_iter, len(obj))
        mfc = color if k % 2 == 0 else 'none'
        mew = 0.5   if k % 2 == 0 else 1.4

        ax_obj.plot(iters, obj, color=color, linestyle=ls,
                    marker=mark, markerfacecolor=mfc,
                    markeredgecolor=color, markeredgewidth=mew,
                    linewidth=1.8, markersize=5.5, zorder=4, label=label)
        ax_obj.plot(iters[-1], obj[-1], marker='*', color=color,
                    markersize=9.5, zorder=5, linestyle='none',
                    markeredgewidth=0.5, markeredgecolor='k')

        ax_db.semilogy(iters, np.maximum(delta, 1e-16),
                       color=color, linestyle=ls, marker=mark,
                       markerfacecolor=mfc, markeredgecolor=color,
                       markeredgewidth=mew,
                       linewidth=1.8, markersize=5.5, zorder=4, label=label)

    if copf_obj is not None:
        ax_obj.axhline(copf_obj, color='black', linestyle='-',
                       linewidth=2.0, zorder=3, label='$P=1$')

    # ── Zoom inset: tail iterations only, y-range from actual data ───────────
    if copf_obj is not None and max_iter > 1:
        if zoom_lo is not None and zoom_hi is not None:
            y_lo, y_hi = zoom_lo, zoom_hi
            x_zoom_lo  = 0.5
        else:
            span_zoom = copf_obj / 200.0
            y_lo = copf_obj - span_zoom
            y_hi = copf_obj + span_zoom
            x_zoom_lo = 0.5

        axin = ax_obj.inset_axes([0.25, 0.09, 0.73, 0.40])
        axin.set_facecolor('white')
        for k, p in enumerate(plot_ps):
            obj_p   = np.asarray(runs[p]['obj_history'], dtype=float)
            iters_p = np.arange(1, len(obj_p) + 1)
            color   = _P_COLORS[k % len(_P_COLORS)]
            mark    = _P_MARKS[k % len(_P_MARKS)]
            ls      = _P_LINES[k % len(_P_LINES)]
            i_mfc   = color if k % 2 == 0 else 'none'
            i_mew   = 0.4   if k % 2 == 0 else 1.1
            axin.plot(iters_p, obj_p, color=color, linestyle=ls, marker=mark,
                      markerfacecolor=i_mfc, markeredgecolor=color,
                      markeredgewidth=i_mew,
                      linewidth=1.2, markersize=4.0, zorder=4)
            axin.plot(iters_p[-1], obj_p[-1], marker='*', color=color,
                      markersize=7.0, zorder=5, linestyle='none',
                      markeredgewidth=0.4, markeredgecolor='k')

        axin.axhline(copf_obj, color='black', linestyle='-',
                     linewidth=1.4, zorder=3)

        axin.set_xlim(x_zoom_lo, max_iter + 0.5)
        axin.set_ylim(y_lo, y_hi)
        axin.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))
        axin.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))
        axin.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
        axin.tick_params(labelsize=6.5, pad=1.5, length=2.0)
        axin.yaxis.tick_right()
        axin.yaxis.set_label_position('right')
        axin.grid(True, linestyle='--', linewidth=0.25, alpha=0.5)
        for spine in axin.spines.values():
            spine.set_linewidth(0.8)

        from matplotlib.lines import Line2D as _L2D
        _p1_handle = _L2D([0], [0], color='black', linestyle='-', linewidth=1.0)
        ax_obj.legend([_p1_handle], [r'$P=1$'],
                      loc='upper right',
                      fontsize=7, handlelength=1.3,
                      borderpad=0.3, framealpha=0.95,
                      edgecolor='0.75', ncol=1)

    # Tolerance reference on ΔB panel
    ax_db.axhline(tol, color='#666666', linestyle=':', linewidth=1.5, zorder=2)

    # ── Panel (a) cosmetics ───────────────────────────────────────────────────
    ax_obj.tick_params(labelbottom=False)
    ax_obj.set_ylabel(f'Objective value ({obj_unit})')
    ax_obj.set_xlim(0.5, max_iter + 0.5)
    ax_obj.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_obj.grid(True, linestyle='--', linewidth=0.3, alpha=0.6)
    ax_obj.spines['top'].set_visible(False)
    ax_obj.spines['right'].set_visible(False)

    if copf_obj is not None:
        ax_obj.annotate(f'{copf_obj:.1f}',
                        xy=(1.0, copf_obj), xycoords=('axes fraction', 'data'),
                        xytext=(3, 0), textcoords='offset points',
                        fontsize=6.5, va='center', ha='left',
                        color='black', fontweight='bold', zorder=7,
                        annotation_clip=False)

    # ── Panel (b) cosmetics ───────────────────────────────────────────────────
    ax_db.set_xlabel('OTD Iteration $(k)$')
    ax_db.set_ylabel(r'$\text{Max boundary error } \Delta B \text{ (p.u.)}$')
    ax_db.set_xlim(0.5, max_iter + 0.5)
    ax_db.set_ylim(1e-6, 2)
    ax_db.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
    ax_db.yaxis.set_major_locator(mticker.LogLocator(base=10))
    ax_db.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
    ax_db.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
    ax_db.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.35)
    ax_db.spines['top'].set_visible(False)
    ax_db.spines['right'].set_visible(False)
    ax_db.tick_params(axis='y', which='both', direction='in')

    # ── Partition legend (P>1) horizontally between the two subplots ──────────
    handles, labels = ax_obj.get_legend_handles_labels()
    p_pairs = [(h, l) for h, l in zip(handles, labels) if l != '$P=1$']
    if p_pairs:
        h_p, l_p = zip(*p_pairs)
        leg = fig.legend(h_p, l_p,
                         loc='center',
                         bbox_to_anchor=(0.57, 0.510),
                         ncol=len(h_p),
                         fontsize=7,
                         handlelength=1.2,
                         borderpad=0.35,
                         labelspacing=0.2,
                         columnspacing=0.3,
                         framealpha=0.95,
                         edgecolor='0.8')
        leg.set_zorder(10)

    return _savefig_dddp(fig, out_path)


def plot_dddp_partition_timing(run_logs_dir, system_name,
                                partition_list=None,
                                model_tag='isocp',
                                out_path='dddp_partition_timing.pdf',
                                copf_total_s=None):
    """Two-panel computation-time figure comparing DDDP-OTD across partitions.

    Panel (a) — Total wall-clock time per partition P.
      Bars are colour-coded (converged = blue, not converged = grey).
      If P = 1 data is available (or ``copf_total_s`` is supplied), a red
      dashed COPF reference line is drawn and a speedup annotation is placed
      on each bar.

    Panel (b) — Number of Benders iterations to convergence per partition.
      Each bar is annotated with the exact iteration count.

    Parameters
    ----------
    run_logs_dir  : str    path to directory containing the pkl files.
    system_name   : str    e.g. 'IEEE_123'
    partition_list: list   of ints, or None to auto-discover.
    out_path      : str    output file (pdf / png).  Relative → Plot/ folder.
    copf_total_s  : float  centralized COPF wall time (s).  Overrides P=1 pkl.
    """
    import numpy as np
    import matplotlib.ticker as mticker

    plt.rcParams.update(_IEEE_RC)

    # COPF time
    runs = _load_dddp_runs(run_logs_dir, system_name, partition_list,
                           model_tag=model_tag)
    if not runs:
        raise FileNotFoundError(f"No DDDP pkl files found in {run_logs_dir}")

    # COPF time
    if copf_total_s is None and 1 in runs:
        copf_total_s = runs[1]['total_s']

    bar_ps     = sorted(p for p in runs if p != 1)
    times      = np.asarray([runs[p]['total_s'] for p in bar_ps])
    niters     = np.asarray([runs[p]['n_iters']  for p in bar_ps], dtype=int)
    conv       = [runs[p].get('converged', True) for p in bar_ps]
    xlabels    = [f'$P={p}$' for p in bar_ps]
    x          = np.arange(len(bar_ps))
    bar_w      = 0.52
    bar_colors = [_P_COLORS[k % len(_P_COLORS)] if c else '#aaaaaa'
                  for k, c in enumerate(conv)]

    fig, (ax_t, ax_n) = plt.subplots(
        2, 1, figsize=(3.5, 2.8),
        gridspec_kw={'hspace': 0.12},
        constrained_layout=False,
    )
    fig.subplots_adjust(left=0.17, right=0.97, top=0.96, bottom=0.10,
                        hspace=0.16)

    # ── Single panel: bars = total time (left y), line = iterations (right y) ─
    ax_t.set_xlim(-0.55, len(bar_ps) - 0.45)
    ax_iter = ax_t.twinx()   # right y-axis for iteration count

    # Bars — total time
    bars = ax_t.bar(x, times, width=bar_w, color=bar_colors,
                    edgecolor='white', linewidth=0.5, zorder=3, alpha=0.85)

    y_max = max(times.max(), copf_total_s if copf_total_s else 0) * 1.15

    if copf_total_s is not None:
        ax_t.axhline(copf_total_s, color='#000000', linestyle='--',
                     linewidth=1.2, zorder=4, label=f'COPF: {copf_total_s:.1f} s')

    ax_t.set_xticks(x)
    ax_t.set_xticklabels(xlabels)
    ax_t.set_xlabel('Partitions $P$')
    ax_t.set_ylabel('Total Time (s)')
    ax_t.set_ylim(0, y_max)
    ax_t.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
    ax_t.grid(True, axis='y', linestyle='--', linewidth=0.3, alpha=0.5)
    ax_t.spines['top'].set_visible(False)
    ax_t.tick_params(axis='both', direction='in')

    # Line + markers — iteration count on right axis
    ax_iter.plot(x, niters, color='#333333', linestyle='-',
                 marker='o', markerfacecolor='#333333', markeredgecolor='#333333',
                 linewidth=1.4, markersize=5, zorder=5, label='DDDP Iterations')

    ax_iter.set_ylabel('DDDP Iterations', color='#333333')
    ax_iter.tick_params(axis='y', colors='#333333', direction='in')
    ax_iter.set_ylim(0, niters.max() * 1.30)
    ax_iter.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=5))
    ax_iter.spines['top'].set_visible(False)

    # Combined legend
    h1, l1 = ax_t.get_legend_handles_labels()
    h2, l2 = ax_iter.get_legend_handles_labels()
    ax_t.legend(h1 + h2, l1 + l2,
                bbox_to_anchor=(0.96, 0.96), bbox_transform=fig.transFigure,
                loc='upper right', fontsize=7,
                framealpha=0.9, edgecolor='0.8', borderpad=0.4,
                handlelength=1.4, labelspacing=0.2)

    # ── Hide the unused second subplot panel ──────────────────────────────────
    ax_n.set_visible(False)

    return _savefig_dddp(fig, out_path)


# ── ADMM temporal convergence (primal + dual residuals) ──────────────────────
def plot_admm_convergence(run_logs_dir, system_name,
                          partition_list=None,
                          out_path='admm_convergence.pdf'):
    """Two-panel convergence figure for ADMM temporal decomposition.

    Panel (a): primal residual (coupling mismatch) vs ADMM iteration.
    Panel (b): dual residual vs ADMM iteration.

    Loads  run_logs/admm_{system_name}_P{p}_admm.pkl  for each P.
    """
    import pickle, glob, re
    import numpy as np
    import matplotlib.ticker as mticker

    plt.rcParams.update(_IEEE_RC)

    if partition_list is None:
        pattern = os.path.join(run_logs_dir, f'admm_{system_name}_P*_admm.pkl')
        found   = sorted(glob.glob(pattern))
        partition_list = []
        for path in found:
            m = re.search(r'_P(\d+)_', path)
            if m:
                partition_list.append(int(m.group(1)))

    runs = {}
    for p in partition_list:
        path = os.path.join(run_logs_dir, f'admm_{system_name}_P{p}_admm.pkl')
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                runs[p] = pickle.load(f)

    if not runs:
        raise FileNotFoundError(
            f"No ADMM pkl files found in {run_logs_dir}")

    plot_ps  = sorted(runs)
    max_iter = max(len(runs[p]['primal_res_hist']) for p in plot_ps)

    fig, (ax_p, ax_d) = plt.subplots(
        2, 1, figsize=(3.5, 4.0),
        gridspec_kw={'hspace': 0.12},
        constrained_layout=False,
    )
    fig.subplots_adjust(left=0.15, right=0.97, top=0.96, bottom=0.09,
                        hspace=0.45)

    for k, p in enumerate(plot_ps):
        d      = runs[p]
        pr     = np.asarray(d['primal_res_hist'], dtype=float)
        dr     = np.asarray(d['dual_res_hist'],   dtype=float)
        iters  = np.arange(1, len(pr) + 1)
        color  = _P_COLORS[k % len(_P_COLORS)]
        mark   = _P_MARKS[k % len(_P_MARKS)]
        ls     = _P_LINES[k % len(_P_LINES)]
        label  = f'$P = {p}$'
        mfc    = color if k % 2 == 0 else 'none'
        mew    = 0.5   if k % 2 == 0 else 1.4

        ax_p.semilogy(iters, np.maximum(pr, 1e-16),
                      color=color, linestyle=ls, marker=mark,
                      markerfacecolor=mfc, markeredgecolor=color,
                      markeredgewidth=mew,
                      linewidth=1.8, markersize=5.5, label=label)
        ax_d.semilogy(iters, np.maximum(dr, 1e-16),
                      color=color, linestyle=ls, marker=mark,
                      markerfacecolor=mfc, markeredgecolor=color,
                      markeredgewidth=mew,
                      linewidth=1.8, markersize=5.5)

    for ax, ylabel in [(ax_p, 'Primal Residual (p.u.)'),
                       (ax_d, 'Dual Residual (p.u.)')]:
        ax.set_xlim(0.5, max_iter + 0.5)
        ax.set_xlabel('ADMM Iteration')
        ax.set_ylabel(ylabel)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=10))
        ax.yaxis.set_major_locator(mticker.LogLocator(base=10))
        ax.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
        ax.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
        ax.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.35)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.tick_params(axis='y', which='both', direction='in')

    ax_p.legend(fontsize=7, framealpha=0.9, edgecolor='0.8',
                borderpad=0.4, handlelength=1.4, labelspacing=0.2)

    return _savefig_dddp(fig, out_path)


# ── Linear vs ISOCP comparison (2×2) ─────────────────────────────────────────
def plot_dddp_linear_vs_isocp(run_logs_dir, system_name,
                               partition_list=None,
                               out_path='dddp_linear_vs_isocp.pdf',
                               tol=1e-3,
                               obj_unit=r'\$'):
    """Double-column 2×2 comparison: Linear BFM (left) vs ISOCP (right).

    Row 1: LB convergence.   Row 2: Relative optimality gap (log).
    Shared colour/marker scheme across all panels.  Single legend between rows.
    """
    import numpy as np
    import matplotlib.ticker as mticker
    from matplotlib.gridspec import GridSpec

    plt.rcParams.update(_IEEE_RC)

    runs_lin   = _load_dddp_runs(run_logs_dir, system_name, partition_list,
                                  model_tag='linear')
    runs_iso   = _load_dddp_runs(run_logs_dir, system_name, partition_list,
                                  model_tag='isocp')

    if not runs_lin and not runs_iso:
        raise FileNotFoundError(f"No DDDP pkl files found in {run_logs_dir}")

    # Union of partitions present in both (skip P=1 COPF reference)
    all_ps   = sorted(set(list(runs_lin.keys()) + list(runs_iso.keys())) - {1})
    max_iter = 0
    for d in list(runs_lin.values()) + list(runs_iso.values()):
        max_iter = max(max_iter, len(d['lb_history']))

    # COPF refs
    def _copf(runs):
        if 1 in runs:
            return float(np.asarray(runs[1]['lb_history'], dtype=float)[-1])
        finals = [float(np.asarray(d['lb_history'], dtype=float)[-1])
                  for d in runs.values() if d.get('converged', False)]
        return max(finals) if finals else None

    copf_lin = _copf(runs_lin)
    copf_iso = _copf(runs_iso)

    # Figure: 7.16" double-column, 2 rows × 2 cols
    fig = plt.figure(figsize=(7.16, 4.5))
    gs  = GridSpec(2, 2, figure=fig, hspace=0.18, wspace=0.22)
    ax_lb_lin  = fig.add_subplot(gs[0, 0])
    ax_lb_iso  = fig.add_subplot(gs[0, 1])
    ax_gap_lin = fig.add_subplot(gs[1, 0])
    ax_gap_iso = fig.add_subplot(gs[1, 1])
    fig.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.10,
                        hspace=0.18, wspace=0.22)

    # Column titles
    ax_lb_lin.set_title('LINEAR', fontsize=8, fontweight='bold', pad=4)
    ax_lb_iso.set_title('ISOCP', fontsize=8, fontweight='bold', pad=4)

    def _plot_col(runs, copf_lb, ax_lb, ax_gap, ylabel_lb=True, ylabel_gap=True):
        for k, p in enumerate(all_ps):
            if p not in runs:
                continue
            d      = runs[p]
            lb     = np.asarray(d['lb_history'], dtype=float)
            gap    = np.asarray(d['gap_rel_history'], dtype=float)[:len(lb)]
            iters  = np.arange(1, len(lb) + 1)
            color  = _P_COLORS[k % len(_P_COLORS)]
            mark   = _P_MARKS[k % len(_P_MARKS)]
            ls     = _P_LINES[k % len(_P_LINES)]
            label  = f'$P = {p}$'

            ax_lb.plot(iters, lb, color=color, linestyle=ls, marker=mark,
                       markerfacecolor=color, markeredgecolor=color,
                       linewidth=1.4, markersize=4.0, zorder=4, label=label)
            ax_lb.plot(iters[-1], lb[-1], marker='*', color=color,
                       markersize=7.0, zorder=5, linestyle='none',
                       markeredgewidth=0.4, markeredgecolor='k')

            ax_gap.semilogy(iters, np.maximum(gap, 1e-16),
                            color=color, linestyle=ls, marker=mark,
                            markerfacecolor=color, markeredgecolor=color,
                            linewidth=1.4, markersize=4.0, zorder=4)

        if copf_lb is not None:
            ax_lb.axhline(copf_lb, color='#000000', linestyle='-',
                          linewidth=1.1, zorder=3)
            ax_lb.text(0.02, copf_lb, 'COPF',
                       transform=ax_lb.get_yaxis_transform(),
                       fontsize=6.5, va='bottom', ha='left',
                       color='#000000', fontweight='bold')

            # Zoom inset — restrict to tail iterations so data fits in the box
            present_ps = [p for p in all_ps if p in runs]
            n_tail_col  = max(3, max_iter * 2 // 5)
            x_zoom_lo_col = max(1, max_iter - n_tail_col + 1)
            tail_lbs_col = []
            for p in present_ps:
                lb_p_c = np.asarray(runs[p]['lb_history'], dtype=float)
                tail_lbs_col.extend(lb_p_c[max(0, len(lb_p_c) - n_tail_col):].tolist())
            t_arr_col = np.array(tail_lbs_col)
            t_min_col = t_arr_col.min()
            t_max_col = max(t_arr_col.max(), copf_lb)
            margin_col = max(abs(t_max_col - t_min_col) * 0.18, 1.0)
            z_lo    = t_min_col - margin_col
            z_hi    = t_max_col + margin_col
            axin = ax_lb.inset_axes([0.52, 0.06, 0.45, 0.38])
            axin.set_facecolor('white')
            for k, p in enumerate(all_ps):
                if p not in runs:
                    continue
                lb_p    = np.asarray(runs[p]['lb_history'], dtype=float)
                iters_p = np.arange(1, len(lb_p) + 1)
                color   = _P_COLORS[k % len(_P_COLORS)]
                mark    = _P_MARKS[k % len(_P_MARKS)]
                ls      = _P_LINES[k % len(_P_LINES)]
                axin.plot(iters_p, lb_p, color=color, linestyle=ls, marker=mark,
                          markerfacecolor=color, markeredgecolor=color,
                          linewidth=0.8, markersize=2.5, zorder=4)
                axin.plot(iters_p[-1], lb_p[-1], marker='*', color=color,
                          markersize=5.0, zorder=5, linestyle='none',
                          markeredgewidth=0.3, markeredgecolor='k')
            axin.axhline(copf_lb, color='#000000', linestyle='-',
                         linewidth=0.8, zorder=3)
            axin.set_xlim(x_zoom_lo_col - 0.5, max_iter + 0.5)
            axin.set_ylim(z_lo, z_hi)
            axin.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=4))
            axin.yaxis.set_major_formatter(mticker.FuncFormatter(
                lambda x, _: f'{x:,.0f}'))
            axin.yaxis.set_major_locator(mticker.MaxNLocator(nbins=3))
            axin.tick_params(labelsize=5.5, pad=1.0, length=1.5)
            axin.grid(True, linestyle='--', linewidth=0.2, alpha=0.5)
            for spine in axin.spines.values():
                spine.set_linewidth(0.5)
            ax_lb.indicate_inset_zoom(axin, edgecolor='#555555',
                                      linewidth=0.5, alpha=0.8)

        # tolerance line
        ax_gap.axhline(tol, color='#666666', linestyle=':', linewidth=1.0,
                       zorder=2)
        ax_gap.text(0.98, tol * 1.4, rf'$\varepsilon\!=\!{tol:.0e}$',
                    transform=ax_gap.get_yaxis_transform(),
                    color='#444444', fontsize=6.5, va='bottom', ha='right',
                    fontweight='bold')

        # cosmetics — LB
        ax_lb.set_xlim(0.5, max_iter + 0.5)
        ax_lb.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))
        ax_lb.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
        ax_lb.grid(True, linestyle='--', linewidth=0.3, alpha=0.6)
        ax_lb.spines['top'].set_visible(False)
        ax_lb.spines['right'].set_visible(False)
        ax_lb.tick_params(labelbottom=False, direction='in', which='both')
        ax_lb.set_ylabel(f'LB ({obj_unit})')

        # cosmetics — gap
        ax_gap.set_xlim(0.5, max_iter + 0.5)
        ax_gap.set_ylim(1e-6, 1.0)
        ax_gap.set_xlabel('Iteration $k$')
        ax_gap.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))
        ax_gap.yaxis.set_major_locator(mticker.LogLocator(base=10))
        ax_gap.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
        ax_gap.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
        ax_gap.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.35)
        ax_gap.spines['top'].set_visible(False)
        ax_gap.spines['right'].set_visible(False)
        ax_gap.tick_params(axis='both', which='both', direction='in')
        ax_gap.set_ylabel(
            r'$\dfrac{\mathrm{UB} - \mathrm{LB}}{\mathrm{UB}}$')

    _plot_col(runs_lin, copf_lin, ax_lb_lin,  ax_gap_lin, ylabel_lb=True,
              ylabel_gap=True)
    _plot_col(runs_iso, copf_iso, ax_lb_iso,  ax_gap_iso, ylabel_lb=False,
              ylabel_gap=False)

    # Share gap y-axis scale
    ax_gap_iso.sharey(ax_gap_lin)
    ax_gap_iso.tick_params(labelleft=False)

    # Single compact legend between rows
    handles, labels = ax_lb_lin.get_legend_handles_labels()
    fig.legend(handles, labels,
               loc='center', bbox_to_anchor=(0.54, 0.518),
               ncol=len(handles),
               fontsize=6.5, handlelength=1.3,
               borderpad=0.3, labelspacing=0.15, columnspacing=0.6,
               framealpha=0.95, edgecolor='0.8')

    return _savefig_dddp(fig, out_path)

###############################################################################
# ISOCP gamma-sweep convergence plot
###############################################################################
def plot_isocp_gamma_sweep(run_logs_dir, system_name,
                            gamma_list=None,
                            out_path='isocp_gamma_sweep.pdf',
                            gap_tol=1e-4):
    """Single-panel convergence plot: max cone-violation vs ISOCP iteration,
    one curve per gamma (CCP interpolation weight).

    Loads  run_logs/isocp_{system_name}_gamma_{val}.pkl  for each gamma.
    If gamma_list is None, auto-discovers all matching files.

    Parameters
    ----------
    run_logs_dir : str
    system_name  : str  e.g. 'IEEE_123'
    gamma_list   : list of floats, or None (auto-discover)
    out_path     : str  output path (relative → workspace root)
    gap_tol      : float  reference tolerance line (default 1e-4)
    """
    import pickle, glob, re
    import numpy as np
    import matplotlib.ticker as mticker

    plt.rcParams.update(_IEEE_RC)

    # ── Load files ────────────────────────────────────────────────────────────
    runs = {}
    if gamma_list is None:
        pattern = os.path.join(run_logs_dir,
                               f'isocp_{system_name}_gamma_*.pkl')
        for path in sorted(glob.glob(pattern)):
            m = re.search(r'_gamma_(\d+p\d+)\.pkl$', path)
            if m:
                g = float(m.group(1).replace('p', '.'))
                with open(path, 'rb') as f:
                    runs[g] = pickle.load(f)
    else:
        for g in gamma_list:
            tag  = f"{g:.2f}".replace('.', 'p')
            path = os.path.join(run_logs_dir,
                                f'isocp_{system_name}_gamma_{tag}.pkl')
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    runs[g] = pickle.load(f)

    if not runs:
        raise FileNotFoundError(
            f"No isocp gamma pkl files found in {run_logs_dir}")

    gammas   = sorted(runs.keys())[:5]    # first 5 gammas only
    max_iter = max(len(runs[g]['isocp_gap_history']) for g in gammas)

    # Use same module-level palette/style as partition plots
    # ── Figure ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(1, 1, figsize=(3.5, 2.8))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.14)

    for k, g in enumerate(gammas):
        gaps  = np.asarray(runs[g]['isocp_gap_history'], dtype=float)
        iters = np.arange(len(gaps))      # 0 = initial (before first cut)
        color = _P_COLORS[k % len(_P_COLORS)]
        mark  = _P_MARKS[k % len(_P_MARKS)]
        ls    = _P_LINES[k % len(_P_LINES)]
        every = max(1, len(gaps) // 8)
        mfc   = color if k % 2 == 0 else 'none'
        mew   = 0.5   if k % 2 == 0 else 1.4
        ax.semilogy(iters, gaps,
                    color=color, linestyle=ls, marker=mark,
                    markerfacecolor=mfc,
                    markeredgecolor=color, markeredgewidth=mew,
                    linewidth=1.8, markersize=5.5, markevery=every,
                    zorder=4,
                    label=rf'$\tau = {g}$')

    # Tolerance reference line
    ax.axhline(gap_tol, color='#555555', linestyle=':', linewidth=1.0, zorder=2)

    # Horizontal dotted line at the shared SOCP starting error, labelled
    init_gap = np.asarray(runs[gammas[0]]['isocp_gap_history'], dtype=float)[0]
    ax.axhline(init_gap, color='#888888', linestyle=':', linewidth=1.0, zorder=2)
    ax.text(0.98, init_gap,
            f'Initial: {init_gap:.3f}',
            transform=ax.get_yaxis_transform(),
            fontsize=7, va='bottom', ha='right',
            color='#444444', fontweight='bold', zorder=5)

    # ── Cosmetics ─────────────────────────────────────────────────────────────
    ax.set_xlabel('MPISOCP Iteration (m)')
    ax.set_ylabel('Max MPISOCP Relaxation Error (p.u.)')
    ax.set_xlim(-0.3, max_iter - 0.7)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=8))
    ax.yaxis.set_major_locator(mticker.LogLocator(base=10))
    ax.yaxis.set_minor_locator(mticker.LogLocator(base=10, subs='auto'))
    ax.grid(True, which='major', linestyle='--', linewidth=0.3, alpha=0.6)
    ax.grid(True, which='minor', linestyle=':', linewidth=0.2, alpha=0.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='both', which='both', direction='in')

    ax.legend(loc='upper right',
              bbox_to_anchor=(1.0, 0.88),
              ncol=1,
              fontsize=7,
              handlelength=1.5,
              borderpad=0.4,
              labelspacing=0.2,
              framealpha=0.9,
              edgecolor='0.8')

    return _savefig_dddp(fig, out_path)



###############################################################################
# Cross-system scalability summary (time + iterations, 123 vs 9500)
###############################################################################

def plot_scalability_summary(
    run_logs_dir,
    systems=('IEEE_123', 'IEEE_9500'),
    system_labels=('IEEE 123-bus', 'IEEE 9500-bus'),
    partition_list=None,
    out_path='scalability_summary.pdf',
    time_unit='s',
):
    """Publication-quality 2×2 grouped-bar scalability figure.

    Columns = test systems (IEEE 123 | IEEE 9500).
    Rows    = metric (total wall time | number of DDDP iterations).

    Each panel shows one pair of grouped bars per P value (P=1 is the
    centralised COPF baseline).  Within each group the left bar is
    Linear BFM and the right bar is ISOCP.

    Non-converged bars are drawn with a diagonal-hatch pattern and
    annotated with a red asterisk (*) so the reader immediately knows
    the result is not reliable.

    A thin vertical dashed separator after P=1 visually distinguishes
    the COPF baseline from the decomposed runs.

    Parameters
    ----------
    run_logs_dir   : str
        Directory containing the ``dddp_*.pkl`` files.
    systems        : tuple[str]
        System identifiers matching the pkl file names.
    system_labels  : tuple[str]
        Human-readable system names for panel titles.
    partition_list : list[int] or None
        Explicit list of P values **including** 1.  If None, all P values
        (including P=1) are auto-discovered.
    out_path       : str
        Output path (pdf / png / svg).  Relative → resolved next to Plotting.py.
    time_unit      : str
        'min' divides seconds by 60 on the time row; 's' keeps raw seconds.
    """
    import numpy as np
    import matplotlib.ticker as mticker
    import matplotlib.patches as mpatches
    from matplotlib.gridspec import GridSpec
    import pickle, glob, re

    plt.rcParams.update(_IEEE_RC)

    # Colour / style per method
    _METHODS = [
        dict(tag='linear', label='Linear BFM',
             color='#444444', ecolor='#222222', hatch=None),
        dict(tag='isocp',  label='ISOCP',
             color='#1f77b4', ecolor='#0d4d80', hatch=None),
    ]
    _NC_HATCH = '////'          # hatch for non-converged bars
    _NC_ALPHA = 0.45            # reduced opacity for non-converged

    bar_w   = 0.38              # width of each individual bar
    n_meth  = len(_METHODS)
    offsets = np.linspace(-(n_meth - 1) * bar_w / 2,
                           (n_meth - 1) * bar_w / 2,
                           n_meth)

    # ── auto-discover P list (include P=1) ───────────────────────────────────
    if partition_list is None:
        pattern = os.path.join(run_logs_dir,
                               f'dddp_{systems[0]}_P*_linear.pkl')
        found   = sorted(glob.glob(pattern))
        partition_list = []
        for path in found:
            m = re.search(r'_P(\d+)_', path)
            if m:
                partition_list.append(int(m.group(1)))
        partition_list = sorted(partition_list)

    n_ps       = len(partition_list)
    x_pos      = np.arange(n_ps)
    time_scale = 1.0 / 60.0 if time_unit == 'min' else 1.0
    time_ylabel = f'Total time ({time_unit})'

    # ── x-axis tick labels — P=1 gets "(COPF)" suffix ────────────────────────
    xlabels = [f'$P={p}$\n(COPF)' if p == 1 else f'$P={p}$'
               for p in partition_list]

    # ── figure layout ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(7.16, 4.2))
    gs  = GridSpec(2, 2, figure=fig,
                   left=0.10, right=0.97,
                   top=0.91,  bottom=0.13,
                   hspace=0.45, wspace=0.30)
    axes = [[fig.add_subplot(gs[r, c]) for c in range(2)] for r in range(2)]
    _panel_labels = [['(a)', '(b)'], ['(c)', '(d)']]

    for col, (sys_id, sys_lbl) in enumerate(zip(systems, system_labels)):
        ax_t = axes[0][col]   # time row
        ax_i = axes[1][col]   # iteration row

        for mi, meth in enumerate(_METHODS):
            tag   = meth['tag']
            color = meth['color']
            ec    = meth['ecolor']
            times, niters, convs = [], [], []

            for p in partition_list:
                path = os.path.join(run_logs_dir,
                                    f'dddp_{sys_id}_P{p}_{tag}.pkl')
                if os.path.isfile(path):
                    with open(path, 'rb') as fh:
                        d = pickle.load(fh)
                    times.append(d['total_s'] * time_scale)
                    niters.append(d['n_iters'])
                    convs.append(d.get('converged', True))
                else:
                    times.append(np.nan)
                    niters.append(0)
                    convs.append(True)

            times  = np.asarray(times,  dtype=float)
            niters = np.asarray(niters, dtype=int)
            convs  = np.asarray(convs,  dtype=bool)
            xb     = x_pos + offsets[mi]

            # Draw each bar individually to handle NC styling per bar
            for k in range(n_ps):
                if np.isnan(times[k]):
                    continue
                nc      = not convs[k]
                alpha   = _NC_ALPHA if nc else 0.88
                hatch   = _NC_HATCH if nc else None
                lbl     = meth['label'] if k == 0 else None   # label once

                # Time bar
                ax_t.bar(xb[k], times[k], width=bar_w,
                         color=color, edgecolor=ec, linewidth=0.5,
                         alpha=alpha, hatch=hatch, zorder=3, label=lbl)
                if nc:
                    ax_t.text(xb[k], times[k] * 1.01, '*',
                              color='#d62728', ha='center', va='bottom',
                              fontsize=9, fontweight='bold', zorder=5)

                # Iteration bar
                ax_i.bar(xb[k], niters[k], width=bar_w,
                         color=color, edgecolor=ec, linewidth=0.5,
                         alpha=alpha, hatch=hatch, zorder=3, label=lbl)
                if nc:
                    ax_i.text(xb[k], niters[k] + 0.15, '*',
                              color='#d62728', ha='center', va='bottom',
                              fontsize=9, fontweight='bold', zorder=5)

        # ── Separator line after P=1 ─────────────────────────────────────────
        if 1 in partition_list:
            sep_x = x_pos[partition_list.index(1)] + 0.5
            for ax in (ax_t, ax_i):
                ax.axvline(sep_x, color='#888888', linestyle=':',
                           linewidth=0.8, zorder=2)

        # ── Cosmetics — time row ──────────────────────────────────────────────
        ax_t.set_title(sys_lbl, fontsize=8, fontweight='bold', pad=3)
        ax_t.text(0.02, 0.97, _panel_labels[0][col],
                  transform=ax_t.transAxes,
                  va='top', ha='left', fontsize=8, fontweight='bold')
        ax_t.set_ylabel(time_ylabel if col == 0 else '')
        ax_t.set_xticks(x_pos)
        ax_t.set_xticklabels([])          # hidden — shared with iter row
        ax_t.set_xlim(-0.6, n_ps - 0.4)
        ax_t.set_ylim(bottom=0)
        ax_t.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
        ax_t.grid(True, axis='y', linestyle='--', linewidth=0.28, alpha=0.5,
                  zorder=0)
        ax_t.spines['top'].set_visible(False)
        ax_t.spines['right'].set_visible(False)
        ax_t.tick_params(axis='both', direction='in')

        # ── Cosmetics — iteration row ─────────────────────────────────────────
        ax_i.text(0.02, 0.97, _panel_labels[1][col],
                  transform=ax_i.transAxes,
                  va='top', ha='left', fontsize=8, fontweight='bold')
        ax_i.set_xlabel('Partitions $P$')
        ax_i.set_ylabel('DDDP Iterations' if col == 0 else '')
        ax_i.set_xticks(x_pos)
        ax_i.set_xticklabels(xlabels, fontsize=6.5)
        ax_i.set_xlim(-0.6, n_ps - 0.4)
        ax_i.set_ylim(bottom=0)
        ax_i.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=5))
        ax_i.grid(True, axis='y', linestyle='--', linewidth=0.28, alpha=0.5,
                  zorder=0)
        ax_i.spines['top'].set_visible(False)
        ax_i.spines['right'].set_visible(False)
        ax_i.tick_params(axis='both', direction='in')

    # ── Shared legend — centred above both columns ────────────────────────────
    # Build proxy handles directly to avoid duplicates from per-bar labelling
    proxy_handles = [
        mpatches.Patch(facecolor=m['color'], alpha=0.88,
                       edgecolor=m['ecolor'], linewidth=0.5, label=m['label'])
        for m in _METHODS
    ]
    proxy_handles.append(
        mpatches.Patch(facecolor='#888888', alpha=_NC_ALPHA,
                       hatch=_NC_HATCH, edgecolor='#555555',
                       linewidth=0.5, label='Not converged')
    )
    fig.legend(handles=proxy_handles,
               loc='upper center',
               bbox_to_anchor=(0.53, 1.005),
               ncol=len(proxy_handles),
               fontsize=7.5,
               handlelength=1.6,
               borderpad=0.4,
               labelspacing=0.25,
               columnspacing=1.0,
               framealpha=0.95,
               edgecolor='0.75')

    return _savefig_dddp(fig, out_path)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import os
    _wd        = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    _run_logs  = os.path.join(_wd, 'run_logs')
    _system    = 'IEEE_123'
    _model_tag = 'isocp_new'
    _tag       = f'dddp_{_system}_{_model_tag}'
    _otd_model_tag = 'isocp'
    _otd_tag       = f'otd_{_system}_{_otd_model_tag}'

    # plot_dddp_partition_lb(
    #     _run_logs, _system,
    #     model_tag=_model_tag,
    #     out_path=f'{_tag}_lb.pdf',
    # )
    # plot_dddp_partition_timing(
    #     _run_logs, _system,
    #     model_tag=_model_tag,
    #     out_path=f'{_tag}_timing.pdf',
    # )
    plot_otd_partition_convergence(
        _run_logs, _system,
        model_tag=_otd_model_tag,
        out_path=f'{_otd_tag}_convergence.pdf',
    )
    # plot_isocp_gamma_sweep(
    #     _run_logs, _system,
    #     out_path=f'isocp_{_system}_gamma_sweep.pdf',
    # )


###############################################################################
# Network topology plot
###############################################################################
def plot_network(bus, branch, gen, bat, data_areas=None,
                 output_pdf="network_plot.pdf",
                 col_width_inches=3.5):
    """
    Publication-quality column-width network plot (IEEE style).

    Saves a vector PDF + 800-DPI PNG via matplotlib.
    Also opens an interactive Plotly view in the browser.

    Node categories
    ---------------
    Bus       : small gray circles (all non-DER, non-substation buses)
    PV + BESS : green circles (DER buses)
    Substation: large red star
    """
    import math
    import matplotlib
    matplotlib.rcParams.update(_IEEE_RC)
    matplotlib.rcParams.update({"axes.spines.top": False, "axes.spines.right": False})
    import matplotlib.pyplot as plt
    import matplotlib.lines as mlines
    import matplotlib.ticker
    from matplotlib.collections import LineCollection

    # ── Build DataFrames ─────────────────────────────────────────────────────
    bus_df     = pd.DataFrame(bus)
    branch_df  = pd.DataFrame(branch)
    gen_df     = pd.DataFrame(gen)
    battery_df = pd.DataFrame(bat)

    # ── Classify buses ───────────────────────────────────────────────────────
    pv_ids  = set(gen_df["id"].astype(int))
    bat_ids = set(battery_df["id"].astype(int))
    der_ids = pv_ids | bat_ids

    swing_rows    = bus_df[bus_df["bus_type"] == "SWING"]
    substation_id = int(swing_rows["id"].values[0]) if not swing_rows.empty else None

    # ── Build initial positions from CSV coords ──────────────────────────────
    bus_pos_raw = {}
    for _, row in bus_df.iterrows():
        bid = int(row["id"])
        bus_pos_raw[bid] = (float(row["longitude"]), float(row["latitude"]))

    # ── Choose layout strategy ───────────────────────────────────────────────
    nonzero_vals = [(x, y) for x, y in bus_pos_raw.values() if abs(x) + abs(y) > 1e-6]
    has_geo = len(nonzero_vals) > 0

    # Detect real geographic coordinates: |lat| ≤ 90 and |lon| ≤ 180
    if has_geo:
        max_abs_lat = max(abs(y) for _, y in nonzero_vals)
        max_abs_lon = max(abs(x) for x, _ in nonzero_vals)
        is_real_geo = (max_abs_lat <= 90) and (max_abs_lon <= 180)
    else:
        is_real_geo = False

    def _build_graph():
        G = nx.Graph()
        for bid in bus_pos_raw:
            G.add_node(bid)
        for _, row in branch_df.iterrows():
            fb, tb = int(row["fb"]), int(row["tb"])
            if fb in bus_pos_raw and tb in bus_pos_raw:
                G.add_edge(fb, tb)
        return G

    if not has_geo or not is_real_geo:
        # No real lat/lon — use Kamada-Kawai graph layout for clean topology view
        print("[plot_network] Using Kamada-Kawai layout for clean topology.")
        G_layout = _build_graph()
        pos_kk = nx.kamada_kawai_layout(G_layout, scale=1.0)
        bus_pos = {bid: (float(pos_kk[bid][0]), float(pos_kk[bid][1])) for bid in pos_kk}
        geo_mode = False
    else:
        # Real geographic coordinates (e.g. IEEE 9500 lat/lon) — use directly
        bus_pos = {bid: xy for bid, xy in bus_pos_raw.items() if abs(xy[0]) + abs(xy[1]) > 1e-6}
        missing = {bid for bid in bus_pos_raw if bid not in bus_pos}
        if missing:
            adj = {bid: [] for bid in bus_pos_raw}
            for _, row in branch_df.iterrows():
                fb, tb = int(row["fb"]), int(row["tb"])
                if fb in adj and tb in adj:
                    adj[fb].append(tb); adj[tb].append(fb)
            for bid in missing:
                nbrs = [n for n in adj.get(bid, []) if n in bus_pos]
                if nbrs:
                    bus_pos[bid] = (
                        sum(bus_pos[n][0] for n in nbrs) / len(nbrs),
                        sum(bus_pos[n][1] for n in nbrs) / len(nbrs),
                    )
                else:
                    xs = [v[0] for v in bus_pos.values()]
                    ys = [v[1] for v in bus_pos.values()]
                    bus_pos[bid] = (sum(xs) / len(xs), sum(ys) / len(ys))
        geo_mode = True

    reg_lon, reg_lat = [], []
    der_lon, der_lat = [], []
    sub_lon, sub_lat = [], []

    for bid, (x, y) in bus_pos.items():
        if bid == substation_id:
            sub_lon.append(x); sub_lat.append(y)
        elif bid in der_ids:
            der_lon.append(x); der_lat.append(y)
        else:
            reg_lon.append(x); reg_lat.append(y)

    # ── Aspect ratio ─────────────────────────────────────────────────────────
    all_lons = [v[0] for v in bus_pos.values()]
    all_lats = [v[1] for v in bus_pos.values()]
    lon_span   = max(all_lons) - min(all_lons) or 1
    lat_span   = max(all_lats) - min(all_lats) or 1
    if geo_mode:
        lat_centre = (max(all_lats) + min(all_lats)) / 2
        cos_lat = math.cos(math.radians(lat_centre))
        lon_m   = lon_span * cos_lat * 111_320
        lat_m   = lat_span * 111_320
        aspect  = lat_m / lon_m
    else:
        cos_lat = 1.0
        aspect  = lat_span / lon_span
    fig_h = col_width_inches  # square canvas

    n_buses = len(bus_df)

    # ── Adaptive sizing ───────────────────────────────────────────────────────
    s_node  = max(3,   min(40,  4500 / n_buses))
    s_der   = s_node
    s_sub   = max(80, s_node * 7)
    lw_edge = max(0.35, min(0.9, 100  / n_buses))
    edge_col = "#111111"
    ms_leg  = max(5, min(9, s_node ** 0.5 * 2.0))

    # ════════════════════════════════════════════════════════════════════════
    fig_mpl, ax = plt.subplots(figsize=(col_width_inches, fig_h),
                               facecolor="white")
    ax.set_facecolor("white")

    # ── Edges ────────────────────────────────────────────────────────────────
    segs = []
    for _, row in branch_df.iterrows():
        fb, tb = int(row["fb"]), int(row["tb"])
        if fb in bus_pos and tb in bus_pos:
            segs.append([bus_pos[fb], bus_pos[tb]])
    lc = LineCollection(segs, colors=edge_col, linewidths=lw_edge,
                        alpha=0.7, zorder=1, rasterized=False)
    ax.add_collection(lc)

    # ── All non-DER buses ─────────────────────────────────────────────────────
    if reg_lon:
        ax.scatter(reg_lon, reg_lat,
                   s=s_node, c="#404040", marker="o",
                   linewidths=0, zorder=2, rasterized=False,
                   label="Bus")

    # ── DER buses — green circles ─────────────────────────────────────────────
    if der_lon:
        ax.scatter(der_lon, der_lat,
                   s=s_der, c="#2CA02C", marker="o",
                   edgecolors="#1a5c1a", linewidths=0.4,
                   zorder=5, rasterized=False,
                   label="PV + BESS")

    # ── Substation — red star ─────────────────────────────────────────────────
    if sub_lon:
        ax.scatter(sub_lon, sub_lat,
                   s=s_sub, c="#CC0000", marker="*",
                   edgecolors="#000000", linewidths=0.9,
                   zorder=6, rasterized=False,
                   label="Substation")

    # ── Axes & ticks ─────────────────────────────────────────────────────────
    # ── Tight auto-limits with 2% padding ────────────────────────────────────
    pad_lon = lon_span * 0.05
    pad_lat = lat_span * 0.05
    ax.set_xlim(min(all_lons) - pad_lon, max(all_lons) + pad_lon)
    ax.set_ylim(min(all_lats) - pad_lat, max(all_lats) + pad_lat)
    ax.axis("off")

    # ── Legend ────────────────────────────────────────────────────────────────
    leg_handles = [
        mlines.Line2D([], [], color="#404040", marker="o", markersize=ms_leg,
                      linestyle="None", label="Bus"),
        mlines.Line2D([], [], color="#2CA02C", marker="o", markersize=ms_leg + 1,
                      linestyle="None", markeredgecolor="#1a5c1a",
                      markeredgewidth=0.5, label="PV + BESS"),
        mlines.Line2D([], [], color="#CC0000", marker="*", markersize=ms_leg + 3,
                      linestyle="None", markeredgecolor="#000000",
                      markeredgewidth=0.9, label="Substation"),
    ]
    ax.legend(handles=leg_handles,
              loc="lower right", framealpha=0.97,
              edgecolor="#AAAAAA", frameon=True,
              borderpad=0.7, labelspacing=0.4, handletextpad=0.5,
              handlelength=1.4, fontsize=9)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # ── Save PDF + PNG ────────────────────────────────────────────────────────
    out_png = output_pdf.replace(".pdf", ".png")
    try:
        fig_mpl.savefig(output_pdf, format="pdf", dpi=800, bbox_inches="tight", pad_inches=0.02)
        print(f"[plot_network] Saved {output_pdf}")
    except Exception as e:
        print(f"[plot_network] PDF save failed: {e}")
    try:
        fig_mpl.savefig(out_png, format="png", dpi=800, bbox_inches="tight", pad_inches=0.02)
        print(f"[plot_network] Saved {out_png}")
    except Exception as e:
        print(f"[plot_network] PNG save failed: {e}")

    plt.show()

    # ════════════════════════════════════════════════════════════════════════
    # Plotly — interactive browser view
    # ════════════════════════════════════════════════════════════════════════
    edge_x, edge_y = [], []
    for _, row in branch_df.iterrows():
        fb, tb = int(row["fb"]), int(row["tb"])
        if fb in bus_pos and tb in bus_pos:
            x0, y0 = bus_pos[fb]
            x1, y1 = bus_pos[tb]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=0.7, color="#707070"),
        hoverinfo="none", showlegend=False
    ))
    fig.add_trace(go.Scatter(
        x=reg_lon, y=reg_lat, mode="markers",
        marker=dict(size=4, color="#303030", symbol="circle",
                    opacity=0.85, line=dict(width=0)),
        name="Bus", hoverinfo="skip"
    ))
    fig.add_trace(go.Scatter(
        x=der_lon, y=der_lat, mode="markers",
        marker=dict(size=9, color="#2CA02C", symbol="circle",
                    line=dict(color="#1a5c1a", width=0.8)),
        name="PV + BESS",
        hovertemplate="<b>PV + BESS</b><extra></extra>"
    ))
    if sub_lon:
        sub_name = bus_df.loc[bus_df["id"] == substation_id, "name"].values[0]
        fig.add_trace(go.Scatter(
            x=sub_lon, y=sub_lat, mode="markers",
            marker=dict(size=14, color="#CC0000", symbol="star",
                        line=dict(color="black", width=1.0)),
            name="Substation",
            hovertemplate=f"<b>Substation</b><br>{sub_name}<extra></extra>"
        ))

    fig.update_layout(
        template="plotly_white",
        showlegend=True,
        xaxis=dict(title="Longitude", showgrid=False, zeroline=False),
        yaxis=dict(title="Latitude" if geo_mode else "",
                   showgrid=False, zeroline=False,
                   scaleanchor="x",
                   scaleratio=1.0 / cos_lat),
        margin=dict(l=60, r=20, t=20, b=60),
        legend=dict(x=0.01, y=0.01, xanchor="left", yanchor="bottom",
                    bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="#BBBBBB", borderwidth=1),
        font=dict(family="Times New Roman, serif", size=13),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    fig.show()


