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
    fig.write_image(filepath,format='pdf',scale=4)

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
    df["node"] = df["node"].astype(int)
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
            time, (fb, tb), phase = key
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
    df["fb"] = df["fb"].astype(int)
    df["tb"] = df["tb"].astype(int)
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
            time, (fb, tb), phase = key
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
    df["fb"] = df["fb"].astype(int)
    df["tb"] = df["tb"].astype(int)
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
