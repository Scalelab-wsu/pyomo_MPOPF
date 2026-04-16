import plotly.express as px
import plotly.graph_objects as go
import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import itertools
plt.rcParams.update({
    "font.family": "Times New Roman",
    "font.size": 12,
    "axes.titlesize": 12,
    "axes.labelsize": 12,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12
})

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
    # fig.write_html(filepath,full_html=True)
    fig.write_image(filepath, format='png',scale=4)

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
    df["node_num"] = df["node"]
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
    # NEW: optional filters/ordering
    bfs_edges = modelVals_list.get("bfs", {}).get("bfs_edges")
    agg_nodes = set(modelVals_list.get("aggregated_nodes", []) or [])

    # Only use kwargs that actually contain power-flow data
    data_models = {k: v for k, v in modelVals_list.items()
                   if isinstance(v, dict) and ("Q" in v)}
    if not data_models:
        raise ValueError("No model dicts with key 'Q' provided.")

    # Keys common to all scenarios
    common_q_keys = set.intersection(*[set(mv["Q"].keys()) for mv in data_models.values()])

    # Keep only lines whose TO bus is in aggregated_nodes (if provided)
    if agg_nodes:
        common_q_keys = {k for k in common_q_keys if k[1][1] in agg_nodes}

    # Gather data
    rows = []
    for scenario_name, mv in data_models.items():
        scenario_label = scenario_name.replace("Vals", "")
        for time, fb, tb, phase in common_q_keys:
            rows.append({
                "time": f"t={time}",
                "fb": fb,
                "tb": tb,
                "branch_label": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": mv["Q"][(time, fb, tb, phase)],
            })

    df = pd.DataFrame(rows)

    # Order branches by BFS edges, filtered to aggregated_nodes if given
    if bfs_edges:
        order = []
        for f, t in bfs_edges:
            if agg_nodes and t not in agg_nodes:
                continue
            order.append(f"{f}->{t}")
        # keep only edges present in df
        present = set(df["branch_label"].unique())
        order = [e for e in order if e in present]
        df["branch_label"] = pd.Categorical(df["branch_label"], categories=order, ordered=True)
    else:
        # Fallback: avoid zig-zag — sort by to_bus, then from_bus
        df = df.sort_values(["tb"]).reset_index(drop=True)
        order = pd.unique(df["branch_label"])
        df["branch_label"] = pd.Categorical(df["branch_label"], categories=order, ordered=True)

    category_order = list(df["branch_label"].cat.categories)

    df = df.sort_values("branch_label")

    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)

    fig = px.line(
        df,
        # df[df["time"] == "t=16"],
        x="branch_label", y="value",
        color="scenario",
        line_dash="time" if len(data_models) > 1 else None,
        facet_col="phase",
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        line_dash_map=line_dash_map_dynamic,
        category_orders={"branch_label": category_order},
        markers=True
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 20, "t": 25, "b": 10},
        yaxis_title="Q (kVar)",
        font_color="black",
        legend_xref="paper",
        legend_title_text="",
        legend_orientation="h",
        legend_borderwidth=1,
        legend=dict(x=0, y=1, xanchor="left", yanchor="top",
                    bgcolor="rgba(255,255,255,0.5)"),
        font=dict(size=12, family="Times New Roman"),
    )
    fig.update_xaxes(showticklabels=False)
    fig.update_traces(marker=dict(size=3), line=dict(width=1))
    save_plot(fig, "reactive_power_flows.png")
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
    df["node_num"] = df["node"]
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
    df["node_num"] = df["node"]
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
    # NEW: optional filters/ordering
    bfs_edges = modelVals_list.get("bfs", {}).get("bfs_edges")
    agg_nodes = set(modelVals_list.get("aggregated_nodes", []) or [])

    # Only use kwargs that actually contain power-flow data
    data_models = {k: v for k, v in modelVals_list.items()
                   if isinstance(v, dict) and ("P" in v)}
    if not data_models:
        raise ValueError("No model dicts with key 'P' provided.")

    # Keys common to all scenarios
    common_p_keys = set.intersection(*[set(mv["P"].keys()) for mv in data_models.values()])

    # Keep only lines whose TO bus is in aggregated_nodes (if provided)
    if agg_nodes:
        common_p_keys = {k for k in common_p_keys if k[1][1] in agg_nodes}

    # Gather data
    rows = []
    for scenario_name, mv in data_models.items():
        scenario_label = scenario_name.replace("Vals", "")
        for time, fb, tb, phase in common_p_keys:
            rows.append({
                "time": f"t={time}",
                "fb": fb,
                "tb": tb,
                "branch_label": f"{fb}->{tb}",
                "phase": phase,
                "scenario": scenario_label,
                "value": mv["P"][(time, fb, tb, phase)],
            })

    df = pd.DataFrame(rows)

    # Order branches by BFS edges, filtered to aggregated_nodes if given
    if bfs_edges:
        order = []
        for f, t in bfs_edges:
            if agg_nodes and t not in agg_nodes:
                continue
            order.append(f"{f}->{t}")
        # keep only edges present in df
        present = set(df["branch_label"].unique())
        order = [e for e in order if e in present]
        df["branch_label"] = pd.Categorical(df["branch_label"], categories=order, ordered=True)
    else:
        # Fallback: avoid zig-zag — sort by to_bus, then from_bus
        df = df.sort_values(["tb"]).reset_index(drop=True)
        order = pd.unique(df["branch_label"])
        df["branch_label"] = pd.Categorical(df["branch_label"], categories=order, ordered=True)

    category_order = list(df["branch_label"].cat.categories)
    df = df.sort_values("branch_label")

    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)

    fig = px.line(
        df,
        # df[df["time"] == "t=16"],
        x="branch_label", y="value",
        color="scenario",
        line_dash="time" if len(data_models) > 1 else None,
        facet_col="phase",
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        line_dash_map=line_dash_map_dynamic,
        category_orders={"branch_label": category_order},
        markers=True
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 20, "t": 25, "b": 10},
        yaxis_title="P (kW)",
        yaxis=dict(range=[df['value'].min(), df['value'].max()]),  # Set the y-axis range),
        font_color="black",
        legend_xref="paper",
        legend_title_text="",
        legend_orientation="h",
        legend_borderwidth=1,
        legend=dict(x=0, y=1, xanchor="left", yanchor="top",
                    bgcolor="rgba(255,255,255,0.5)"),
        font=dict(size=12, family="Times New Roman"),
    )
    fig.update_xaxes(showticklabels=False)
    fig.update_traces(marker=dict(size=3), line=dict(width=1))
    save_plot(fig, "active_power_flows.png")
    fig.show()




###############################################################################
# 7) plot_voltage
###############################################################################
def plot_voltage(**modelVals_list):
    # NEW: get bfs order and aggregated nodes (optional)
    bfs_order = modelVals_list.get("bfs", {}).get("bfs_nodes")
    agg_nodes = set(modelVals_list.get("aggregated_nodes", []) or [])

    # Ignore non-data kwargs (like bfs/aggregated_nodes) when building common keys
    data_models = {k: v for k, v in modelVals_list.items()
                   if isinstance(v, dict) and ("v" in v)}

    if not data_models:
        raise ValueError("No model dicts with key 'v' provided.")

    # Only keep keys common to all scenarios
    common_v_keys = set.intersection(*[set(mv["v"].keys()) for mv in data_models.values()])

    data = []
    for scenario_name, mv in data_models.items():
        scenario_label = scenario_name.replace("Vals", "")
        for (time, node, phase) in common_v_keys:
            # NEW: keep only aggregated nodes if provided
            if agg_nodes and node not in agg_nodes:
                continue
            val = mv["v"][(time, node, phase)]
            data.append({
                "time": f"t={time}",
                "nodes": node,
                "phase": phase,
                "scenario": scenario_label,
                "value": val
            })

    df = pd.DataFrame(data)

    # NEW: order nodes by BFS, but only those in aggregated list if given
    if bfs_order:
        order = [n for n in bfs_order if (not agg_nodes) or (n in agg_nodes)]
        df["nodes"] = pd.Categorical(df["nodes"], categories=order, ordered=True)

    df = df.sort_values(by="nodes")

    scenarios = sorted(df["scenario"].unique())
    color_map_dynamic, symbol_map_dynamic, line_dash_map_dynamic = generate_dynamic_maps(scenarios)

    fig = px.scatter(
        df,
        # df[df["time"] == "t=16"],
        x="nodes",
        y="value",
        color="scenario",
        symbol="scenario" if len(data_models) > 1 else None,
        color_discrete_map=color_map_dynamic,
        symbol_map=symbol_map_dynamic,
        labels={"value": "Voltage (pu)"},
        category_orders={"phase": ["a", "b", "c"], "scenario": ["copf", "admm", "enapp"]},
        facet_row="phase",
    )
    fig.update_xaxes(showticklabels=False)
    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 20, "t": 25, "b": 10},
        xaxis_title="nodes",
        yaxis_title="Voltage (pu)",
        font_color="black",
        legend_xref="paper",
        legend_title_text="",
        legend_orientation="v",
        legend_borderwidth=1,
        yaxis_matches="y",
        legend_x=0.95,
        legend_y=-0.2,
        legend=dict(x=0, y=0.8, xanchor="left", yanchor="top",
                    bgcolor="rgba(255,255,255,0.5)"),
        font=dict(size=12, family="Times New Roman"),
    )
    fig.update_traces(marker=dict(size=4), line=dict(width=1))
    save_plot(fig, "voltage_plot.png")
    fig.show()


def plot_network(bus, branch, gen=None, bat=None, data_areas=None):
    """
    Plots the distribution network with:
    - Area-specific nodes in the legend.
    - Generators, batteries, switches with fixed colors.
    - **Substation marked uniquely** as a **larger black star**.
    - **Nodes with both a battery & generator assigned a distinct color and shape.**
    - **No title**, and all nodes have a black border.
    """
    # Convert dictionaries to DataFrames
    bus_df = pd.DataFrame(bus)
    branch_df = pd.DataFrame(branch)
    gen_df = pd.DataFrame(gen)
    battery_df = pd.DataFrame(bat)

    # Identify the substation bus
    substation_bus = None
    if not bus_df[bus_df["bus_type"] == "SWING"].empty:
        substation_bus = bus_df.loc[bus_df["bus_type"] == "SWING", "name"].values[0]

    # Assign each area a unique color
    if data_areas is None:
        data_areas = {}

    area_colors = ["green", "purple", "cyan", "magenta", "yellow", "brown", "pink"]
    all_area_names = list(data_areas.keys())
    area_color_map = {area_name: area_colors[i % len(area_colors)] for i, area_name in enumerate(all_area_names)}

    # Map nodes to areas
    node_area_map = {}
    for area_name, area_info in data_areas.items():
        color_for_this_area = area_color_map[area_name]
        for node_id in area_info["Nset"]:
            node_area_map[node_id] = {"area_name": area_name, "area_color": color_for_this_area}

    # Identify Switch Nodes
    # switch_nodes = set(branch_df[branch_df["type"] == "switch"]["fb"]).union(
    #     set(branch_df[branch_df["type"] == "switch"]["tb"])
    # )

    # Create the Graph
    G = nx.Graph()
    bus_positions = {row["name"]: (row["longitude"], row["latitude"]) for _, row in bus_df.iterrows()}

    for bus_name, pos in bus_positions.items():
        G.add_node(
            bus_name, pos=pos, bus_type=bus_df.loc[bus_df["name"] == bus_name, "bus_type"].values[0],
            has_gen=False, has_battery=False, is_switch=False, is_substation=(bus_name == substation_bus)
        )

    for _, row in gen_df.iterrows():
        gen_name = row["name"]
        G.add_node(gen_name, pos=bus_positions.get(gen_name, (0, 0)), has_gen=True, has_battery=False, is_switch=False)

    for _, row in battery_df.iterrows():
        battery_name = row["name"]
        if battery_name in G.nodes:
            G.nodes[battery_name]["has_battery"] = True
        else:
            G.add_node(battery_name, pos=bus_positions.get(battery_name, (0, 0)), has_gen=False, has_battery=True, is_switch=False)

    # for switch_id in switch_nodes:
    #     if switch_id in G.nodes:
    #         G.nodes[switch_id]["is_switch"] = True

    for _, row in branch_df.iterrows():
        if row["from_name"] in G.nodes and row["to_name"] in G.nodes:
            G.add_edge(row["from_name"], row["to_name"], branch_type=row["type"])

    # Prepare Edge Data
    edge_x, edge_y = [], []
    for u, v in G.edges:
        x0, y0 = G.nodes[u]["pos"]
        x1, y1 = G.nodes[v]["pos"]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    # Prepare Node Data
    node_x, node_y, node_text, node_colors, node_shapes, node_sizes = [], [], [], [], [], []
    node_area_labels = {}

    for n in G.nodes:
        x, y = G.nodes[n]["pos"]
        node_x.append(x)
        node_y.append(y)

        # Default color/shape for regular buses
        color = "white"
        shape = "circle"
        size = 6  # Default node size

        node_type = G.nodes[n]["bus_type"]

        # Assign special colors/shapes for known types
        if G.nodes[n].get("has_gen", False) and G.nodes[n].get("has_battery", False):
            # 🔹 Nodes with **both a generator & battery** get a unique symbol
            shape, color, node_type, size = "hexagram", "red", "Gen + Battery", 10
        elif G.nodes[n].get("has_gen", False):
            shape, color, node_type = "square", "red", "PV"
        elif G.nodes[n].get("has_battery", False):
            shape, color, node_type = "circle", "blue", "Battery"
        # elif G.nodes[n].get("is_switch", False):
        #     shape, color, node_type = "diamond", "orange", "Switch"
        elif G.nodes[n].get("is_substation", False):
            shape, color, node_type, size = "star", "yellow", "Substation", 14
        elif n in node_area_map:
            color = node_area_map[n]["area_color"]
            node_area_labels[color] = node_area_map[n]["area_name"]

        node_colors.append(color)
        node_shapes.append(shape)
        node_sizes.append(size)
        node_text.append(f"Bus {n} - Type: {node_type}")

    # Build the Plotly Figure
    fig = go.Figure()

    # --- Edges ---
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1, color="black"),
        hoverinfo="none",
        mode="lines",
        name="Edges"
    ))

    # Unique (shape, color) combinations
    unique_shape_color = sorted(set(zip(node_shapes, node_colors, node_sizes)))

    for (shape, color, size) in unique_shape_color:
        idxs = [i for i, (s, c, sz) in enumerate(zip(node_shapes, node_colors, node_sizes)) if s == shape and c == color and sz == size]
        scatter_x = [node_x[i] for i in idxs]
        scatter_y = [node_y[i] for i in idxs]
        scatter_text = [node_text[i] for i in idxs]

        # Assign legend names
        if shape == "square" and color == "red":
            legend_name = "PV"
        elif shape == "circle" and color == "blue":
            legend_name = "Batteries"
        # elif shape == "diamond" and color == "orange":
        #     legend_name = "Switches"
        elif shape == "hexagram" and color == "red":
            legend_name = "PV + Battery"  # 🔹 New category for combined nodes
        elif shape == "star" and color == "yellow":
            legend_name = "Substation bus"
        elif color in node_area_labels:
            legend_name = f"{node_area_labels[color].upper()}"
        else:
            legend_name = "Regular Buses"

        fig.add_trace(go.Scatter(
            x=scatter_x,
            y=scatter_y,
            mode="markers",
            marker=dict(size=size, symbol=shape, color=color, line=dict(color="black", width=1.5)),
            text=scatter_text,
            hoverinfo="text",
            name=legend_name
        ))

    fig.update_layout(
        title="",  # No title to save space
        showlegend=True,
        xaxis=dict(title="Longitude"),
        yaxis=dict(title="Latitude"),
        margin=dict(l=5, r=5, t=5, b=5),  # 🔹 Minimize extra space
        autosize=True,
        template="plotly_white",
        legend=dict(
            x=0.5, y=-0.2,  # 🔹 Moves legend up
            xanchor="center", yanchor="top",
            orientation="h",# 🔹 Horizontal legend to reduce height
        ),
    )
    fig.update_layout(font=dict(size=16, family="Times New Roman"))
    fig.write_image("network_plot_agg.png",scale=4,width = 700, height = 500)
    fig.show()

def plot_input_profiles(**profiles_dict):
    """
    Example:
    plot_input_profiles(
        Load_profile=data['loadshape'],
        PV_profile=data['pvshape'],
        Cost_profile=data['costshape']
    )
    """
    fig, ax1 = plt.subplots(figsize=(6, 3.2), dpi=600)

    # --- Left axis: Load & PV ---
    for name, profile in profiles_dict.items():
        if "cost" not in name.lower():
            if "load" in name.lower():
                marker_style, color = 'o', "tab:blue"
            elif "pv" in name.lower():
                marker_style, color = '^', "tab:orange"
            else:
                marker_style, color = 'd', None

            ax1.plot(profile.keys(), profile.values(),
                     label=name.replace("_", " "),
                     linewidth=2.0,
                     color=color,
                     marker=marker_style,
                     markersize=6,       # Bigger markers for clarity
                     markevery=1,        # Marker at every data point
                     markerfacecolor='white',
                     markeredgewidth=1.2)
    ax1.set_xlabel("Time (h)")
    ax1.set_ylabel("Load & PV Multipliers")
    ax1.grid(alpha=0.3, linestyle="--", linewidth=0.6)

    # --- Right axis: Cost ---
    ax2 = ax1.twinx()
    for name, profile in profiles_dict.items():
        if "cost" in name.lower():
            ax2.plot(profile.keys(), profile.values(),
                     label=name.replace("_", " "),
                     color="tab:red",
                     linestyle="--",
                     marker='s',
                     markersize=5.5,
                     linewidth=2.0,
                     markevery=1,
                     markerfacecolor='white',
                     markeredgewidth=1.0)
    ax2.set_ylabel("Cost (Cents/kWh)")

    # --- Combined Legend ---
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2,
               loc="upper center",
               bbox_to_anchor=(0.5, 1.12),
               ncol=3,
               frameon=False,
               fontsize=9)

    plt.tight_layout(pad=0.6)
    plt.savefig("input_profiles.pdf", bbox_inches="tight")
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



