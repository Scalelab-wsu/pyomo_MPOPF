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
    # fig.update_layout(
    #     width=width,  # px width for the figure
    #     height=height,  # px height for the figure
    #     # margin=dict(l=0.1, r=0.1, t=0.1, b=0.1)
    # )
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
    # fig.set_size_inches(width, height)
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
                "time": f"t={time}",
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
    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase), val in mv["B"].items():
            data.append({
                "time": f"t={time}",
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node_num"] = df["node"].astype(int)
    # Sort by numeric node number
    df = df.sort_values(by="node_num")
    fig = px.bar(
        df,
        x="node_num", y="value",
        color="time", facet_col="phase", pattern_shape="scenario" if len(modelVals_list) > 1 else None,
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
                "time": f"t={time}",
                "branch": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    df[["fb", "tb"]] = df["branch"].str.split("->", expand=True)
    df["fb"] = df["fb"]
    df["tb"] = df["tb"]
    df = df.sort_values(["tb"]).reset_index(drop=True)
    df["branch_label"] = df.apply(lambda row: f"{row['fb']}->{row['tb']}", axis=1)
    branch_order = df["branch_label"].unique().tolist()
    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)
    fig = px.line(
        df,
        x="branch_label", y="value",
        color="scenario",
        symbol = "scenario",
        line_dash="time" if len(modelVals_list) > 1 else None,
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
    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase), val in mv["q_D"].items():
            data.append({
                "time": f"t={time}",
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node_num"] = df["node"].astype(int)
    # Sort by numeric node number
    df = df.sort_values(by="node_num")

    fig = px.bar(
        df,
        x="node_num", y="value",
        color="time", facet_col="phase", pattern_shape="scenario" if len(modelVals_list) > 1 else None,
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
    data = []

    # Gather data
    for scenario_name, mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase), val in mv["P_c"].items():
            data.append({
                "time": f"t={time}",
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": -val,   # Negative for charging
                "type": "Charging"
            })
        for (time, node, phase), val in mv["P_d"].items():
            data.append({
                "time": f"t={time}",
                "node": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val,    # Positive for discharging
                "type": "Discharging"
            })
    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["node_num"] = df["node"].astype(int)
    # Sort by numeric node number
    df = df.sort_values(by="node_num")

    fig = px.bar(
        df,
        x="node_num", y="value",
        color="time",
        facet_col="phase",
        pattern_shape="scenario" if len(modelVals_list) > 1 else None,
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
                "time": f"t={time}",
                "branch": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })
    df = pd.DataFrame(data)
    df[["fb", "tb"]] = df["branch"].str.split("->", expand=True)
    df["fb"] = df["fb"]
    df["tb"] = df["tb"]
    df = df.sort_values(["tb"]).reset_index(drop=True)
    df["branch_label"] = df.apply(lambda row: f"{row['fb']}->{row['tb']}", axis=1)
    branch_order = df["branch_label"].unique().tolist()
    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)
    fig = px.line(
        df,
        x="branch_label", y="value",
        color="scenario", line_dash="time" if len(modelVals_list) > 1 else None,
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
    data = []

    common_v_keys = set.intersection(*[set(mv["v"].keys()) for mv in modelVals_list.values()])
    for scenario_name,mv in modelVals_list.items():
        scenario_label = scenario_name.replace("Vals", "")
        for key in common_v_keys:
            time, node, phase = key
            val = mv["v"][key]
            data.append({
                "time": f"t={time}",
                "nodes": node,  # e.g. "node=13"
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })

    df = pd.DataFrame(data)
    # Extract integer node number from the string
    df["nodes"] = df["nodes"].astype(int)
    # Sort by numeric node number
    df = df.sort_values(by="nodes")

    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)

    fig = px.line(
        df,
        # df[df["time"] == "t=16"], ## employ this for just one time plotting to remove mess
        x="nodes",     # use the numeric column on the x-axis
        y="value",
        color="scenario",
        line_dash="scenario",
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
        legend_orientation="h",
        legend_borderwidth=1,
        yaxis_matches="y",
        legend_x=0.95,
        legend_y=-0.2,
        # yaxis_title_standoff = 0.0,
    )
    fig.update_layout(
        legend=dict(
            x=0,  # Horizontal position of legend within the plot (0=left, 1=right)
            y=0.8,  # Vertical position (0=bottom, 1=top)
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

import matplotlib as mpl

# Set global font properties
mpl.rcParams['font.family'] = 'Times New Roman'  # or another preferred font
mpl.rcParams['font.size'] = 12                   # base font size for all text
mpl.rcParams['text.color'] = 'black'
mpl.rcParams['axes.labelcolor'] = 'black'
mpl.rcParams['xtick.color'] = 'black'
mpl.rcParams['ytick.color'] = 'black'
mpl.rcParams['legend.fontsize'] = 12             # legend text size

def plot_convergence(**conv_dict):
    fig, ax = plt.subplots(figsize=(10, 6))

    for name, convergence in conv_dict.items():
        xvalues = list(convergence.keys())
        con = list(convergence.values())
        ax.plot(xvalues, con, label=name)

    ax.set_xlabel('No. of Iterations')
    ax.set_ylabel('Max residual (pu)')
    # ax.set_title('Convergence vs No. of Iterations')
    ax.legend()
    ax.set_yscale('log')

    save_png(fig, "convergence.pdf")
    plt.show()


def plot_objective(**objectives):
    """
    Plot objective trends for each scenario.
    If an objective is given as a dictionary (with iteration keys),
    it plots the trend. If an objective is a constant (float), it plots
    a horizontal line.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    constant_values = []
    for name, objective in objectives.items():
        # Check if the objective is a dictionary (with iterations) or a constant
        if isinstance(objective, dict):
            xvalues = sorted(objective.keys())
            yvalues = [objective[x] for x in xvalues]
            # If all values are the same, plot a horizontal line.
            if len(set(yvalues)) == 1:
                ax.axhline(y=yvalues[0], label=name, linestyle='--', linewidth=2)
            else:
                ax.plot(xvalues, yvalues, label=name)
        else:
            # If it's not a dict (likely a constant float), plot a horizontal line.
            ax.axhline(y=objective, label=name, linestyle='--', linewidth=1, color = 'red')
            xlim_right = ax.get_xlim()[1]
            ax.text(xlim_right * 0.98, objective * 0.98 , f"{objective:.4f}", va="center", ha="right", fontsize=12, color="red")
    # # Add constant values to y-axis ticks
    # if constant_values:
    #     current_ticks = ax.get_yticks().tolist()
    #     updated_ticks = sorted(list(set(current_ticks + constant_values)))
    #     ax.set_yticks(updated_ticks)
    ax.set_xlabel('No. of Iterations')
    ax.set_ylabel('Objective Value')
    # ax.set_title('Objective Value vs No. of Iterations')
    ax.set_yscale('log')
    ax.legend()
    # ax.grid(True, which="both", linestyle="--", linewidth=0.5)

    save_png(fig, "objective.pdf")
    plt.show()

def plot_input_profiles(**profiles_dict):
    fig, ax = plt.subplots(figsize=(10, 6))

    for name, profiles in profiles_dict.items():
        xvalues = list(profiles.keys())
        con = list(profiles.values())
        ax.plot(xvalues, con, label=name)
    ax.legend(loc='lower center',
              bbox_to_anchor=(0.5, 0.95),
              ncol=len(profiles_dict),
              fontsize=12,
              frameon=False)
    ax.set_xlabel('Time (h)')
    ax.set_ylabel('Multipliers')
    # ax.set_title('Convergence vs No. of Iterations')

    save_png(fig, "input_profiles.pdf")
    plt.show()


# def plot_network(bus,branch,gen,bat):
#     bus_data = bus
#     bus_df = pd.DataFrame(bus_data)
#     # Sample Branch DataFrame
#     branch_data = branch
#     branch_df = pd.DataFrame(branch_data)
#     # Sample Generator DataFrame
#     gen_data = gen
#     gen_df = pd.DataFrame(gen_data)
#     # Sample Battery DataFrame
#     battery_data = bat
#     battery_df = pd.DataFrame(battery_data)
#     # Identify Switch Nodes
#     switch_nodes = set(branch_df[branch_df["type"] == "switch"]["fb"]).union(
#         set(branch_df[branch_df["type"] == "switch"]["tb"]))
#     # Create Graph
#     G = nx.Graph()
#     bus_positions = {row["id"]: (row["longitude"], row["latitude"]) for _, row in bus_df.iterrows()}
#     # Add Buses (Regular Nodes)
#     for bus_id, pos in bus_positions.items():
#         G.add_node(bus_id, pos=pos, bus_type=bus_df.loc[bus_df["id"] == bus_id, "bus_type"].values[0], has_gen=False,
#                    has_battery=False, is_switch=False)
#     # Mark Generator Nodes
#     for _, row in gen_df.iterrows():
#         gen_id = row["id"]
#         G.add_node(gen_id, pos=bus_positions.get(gen_id, (0, 0)), has_gen=True, has_battery=False, name=row["name"],
#                    is_switch=False)
#     # Mark Battery Nodes
#     for _, row in battery_df.iterrows():
#         battery_id = row["id"]
#         G.add_node(battery_id, pos=bus_positions.get(battery_id, (0, 0)), has_gen=False, has_battery=True,
#                    name=row["name"],
#                    is_switch=False)
#     # Mark Switch Nodes
#     for switch_id in switch_nodes:
#         if switch_id in G.nodes:
#             G.nodes[switch_id]["is_switch"] = True
#     # Add Branches (Edges)
#     for _, row in branch_df.iterrows():
#         if row["fb"] in G.nodes and row["tb"] in G.nodes:
#             G.add_edge(row["fb"], row["tb"], branch_type=row["type"])
#     # Prepare Edge Data
#     edge_x, edge_y = [], []
#     for u, v in G.edges:
#         x0, y0 = G.nodes[u]["pos"]
#         x1, y1 = G.nodes[v]["pos"]
#         edge_x.extend([x0, x1, None])
#         edge_y.extend([y0, y1, None])
#     # Prepare Node Data
#     node_x, node_y, node_text, node_colors, node_shapes = [], [], [], [], []
#     for n in G.nodes:
#         x, y = G.nodes[n]["pos"]
#         node_x.append(x)
#         node_y.append(y)
#         # Assign colors and shapes based on type
#         if G.nodes[n].get("has_gen", False):
#             node_type = f"Generator - {G.nodes[n].get('name', 'Unknown')}"
#             node_colors.append("red")  # Generator nodes are Red
#             node_shapes.append("square")
#         elif G.nodes[n].get("has_battery", False):
#             node_type = f"Battery - {G.nodes[n].get('name', 'Unknown')}"
#             node_colors.append("blue")  # Battery nodes are Blue
#             node_shapes.append("circle")
#         elif G.nodes[n].get("is_switch", False):
#             node_type = "Switch"
#             node_colors.append("orange")  # Switch nodes are Orange
#             node_shapes.append("diamond")
#         else:
#             node_type = G.nodes[n]["bus_type"]
#             node_colors.append("gray")  # Regular buses are Gray
#             node_shapes.append("circle")
#         node_text.append(f"Bus {n} - Type: {node_type}")  # Hover text
#     # Create Plotly Graph
#     fig = go.Figure()
#     # Add Edges (Always Visible)
#     fig.add_trace(go.Scatter(
#         x=edge_x, y=edge_y,
#         line=dict(width=1, color="black"),
#         hoverinfo="none",
#         mode="lines"
#     ))
#     # Add Generator Nodes (Red Squares)
#     fig.add_trace(go.Scatter(
#         x=[node_x[i] for i in range(len(node_x)) if node_shapes[i] == "square"],
#         y=[node_y[i] for i in range(len(node_y)) if node_shapes[i] == "square"],
#         mode="markers",
#         marker=dict(size=10, symbol="square", color="red"),
#         text=[node_text[i] for i in range(len(node_text)) if node_shapes[i] == "square"],
#         hoverinfo="text",
#         name="Generators"
#     ))
#     # Add Battery Nodes (Blue Circles)
#     fig.add_trace(go.Scatter(
#         x=[node_x[i] for i in range(len(node_x)) if node_shapes[i] == "circle" and node_colors[i] == "blue"],
#         y=[node_y[i] for i in range(len(node_y)) if node_shapes[i] == "circle" and node_colors[i] == "blue"],
#         mode="markers",
#         marker=dict(size=10, symbol="circle", color="blue"),
#         text=[node_text[i] for i in range(len(node_text)) if node_shapes[i] == "circle" and node_colors[i] == "blue"],
#         hoverinfo="text",
#         name="Batteries"
#     ))
#     # Add Switch Nodes (Orange Diamonds)
#     fig.add_trace(go.Scatter(
#         x=[node_x[i] for i in range(len(node_x)) if node_shapes[i] == "diamond"],
#         y=[node_y[i] for i in range(len(node_y)) if node_shapes[i] == "diamond"],
#         mode="markers",
#         marker=dict(size=10, symbol="diamond", color="orange"),
#         text=[node_text[i] for i in range(len(node_text)) if node_shapes[i] == "diamond"],
#         hoverinfo="text",
#         name="Switches"
#     ))
#     # Add Regular Bus Nodes (Gray Circles)
#     fig.add_trace(go.Scatter(
#         x=[node_x[i] for i in range(len(node_x)) if node_shapes[i] == "circle" and node_colors[i] == "gray"],
#         y=[node_y[i] for i in range(len(node_y)) if node_shapes[i] == "circle" and node_colors[i] == "gray"],
#         mode="markers",
#         marker=dict(size=8, symbol="circle", color="gray"),
#         text=[node_text[i] for i in range(len(node_text)) if node_shapes[i] == "circle" and node_colors[i] == "gray"],
#         hoverinfo="text",
#         name="Regular Buses"
#     ))
#     # Layout
#     fig.update_layout(
#         title="Interactive Distribution System Network with Generators, Batteries & Switches",
#         showlegend=True,
#         xaxis=dict(title="Longitude"),
#         yaxis=dict(title="Latitude"),
#         template="plotly_white"
#     )
#     # Show the plot
#     fig.show()

# plot_network has been moved to Plot/Plotting.py

