#
# ## creating barplots
# import plotly.graph_objects as go
# import plotly.express as px
# import os
#
# def save_plot(fig, filename):
#     """
#     Save the plot to the directory where the script is located.
#     """
#     script_dir = os.path.dirname(os.path.abspath(__file__))
#     filepath = os.path.join(script_dir, filename)
#     fig.write_html(filepath)
#
# def plot_substation_power(modelVals):
#     """
#     Plot substation power in separate columns (phases) using a bar plot
#     with a distinct color per phase for easy toggling in the legend.
#     """
#     data = []
#     for (time, phase), value in modelVals["P_subs"].items():
#         # Convert phase to string for discrete color if necessary
#         data.append({
#             "time": time,
#             "phase": str(phase),
#             "value": value
#         })
#
#     fig = px.bar(
#         data,
#         x="time",
#         y="value",
#         color="phase",  # color by phase
#         facet_col="phase",
#         title="Substation Power",
#         labels={"value": "Power (MW)", "time": "Time"},
#         height=400,
#         color_discrete_sequence=px.colors.qualitative.Set1  # Vibrant colors
#     )
#     # Make bars fully opaque, add black outline
#     fig.update_traces(opacity=1, marker_line_width=0, marker_line_color='black')
#
#     save_plot(fig, "P_subs.html")
#     fig.show()
#
# def plot_active_power_flows(modelVals):
#     """
#     Plot active power flows for all branches and phases (line plot).
#     Typically doesn't need the discrete bar color logic, so we leave it as is.
#     """
#     data = []
#     for (time, (fb, tb), phase), value in modelVals["P"].items():
#         data.append({
#             "time": time,
#             "branch": f"{fb}->{tb}",
#             "phase": phase,
#             "value": value
#         })
#
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="branch",
#         facet_col="phase",
#         title="Active Power Flows",
#         labels={"value": "Active Power (MW)", "time": "Time"},
#         height=400
#     )
#     save_plot(fig, "active_power_flows.html")
#     fig.show()
#
# def plot_reactive_power_flows(modelVals):
#     """
#     Plot reactive power flows for all branches and phases (line plot).
#     Typically doesn't need the discrete bar color logic, so we leave it as is.
#     """
#     data = []
#     for (time, (fb, tb), phase), value in modelVals["Q"].items():
#         data.append({
#             "time": time,
#             "branch": f"{fb}->{tb}",
#             "phase": phase,
#             "value": value
#         })
#
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="branch",
#         facet_col="phase",
#         title="Reactive Power Flows",
#         labels={"value": "Reactive Power (MVAR)", "time": "Time"},
#         height=400
#     )
#     save_plot(fig, "reactive_power_flows.html")
#     fig.show()
#
# def plot_der_reactive_power(modelVals):
#     """
#     Plot DER reactive power as a bar plot in separate columns for phases,
#     with each node color-coded using a vibrant discrete sequence.
#     """
#     data = []
#     for (time, node, phase), value in modelVals["q_D"].items():
#         data.append({
#             "time": time,
#             "node": str(node),  # Convert node to string for discrete color
#             "phase": str(phase),
#             "value": value
#         })
#
#     fig = px.bar(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",
#         title="DER Reactive Power",
#         labels={"value": "Reactive Power (MVAR)", "time": "Time"},
#         height=600,
#         barmode="group",
#         color_discrete_sequence=px.colors.qualitative.Set1
#     )
#     fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)
#
#     save_plot(fig, "DER_reactive_power.html")
#     fig.show()
#
# def plot_battery_charging_discharging_combined(modelVals):
#     """
#     Plot battery charging (negative bar) & discharging (positive bar) in separate
#     columns (phases), with each node color-coded in a vibrant discrete palette.
#     """
#     data = []
#     # Charging data (negative)
#     for (time, node, phase), value in modelVals["P_c"].items():
#         data.append({
#             "time": time,
#             "node": str(node),
#             "phase": str(phase),
#             "value": -value,
#             "type": "Charging"
#         })
#
#     # Discharging data (positive)
#     for (time, node, phase), value in modelVals["P_d"].items():
#         data.append({
#             "time": time,
#             "node": str(node),
#             "phase": str(phase),
#             "value": value,
#             "type": "Discharging"
#         })
#
#     fig = px.bar(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",
#         title="Battery Charging and Discharging Power",
#         labels={"value": "Power (MW)", "time": "Time"},
#         height=400,
#         color_discrete_sequence=px.colors.qualitative.Set1
#     )
#
#     # 'relative' mode so negative bars go below axis, positive above
#     fig.update_layout(barmode='relative')
#     fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)
#
#     save_plot(fig, "Battery_Charging_Discharging_Combined.html")
#     fig.show()
#
# def plot_battery_soc(modelVals):
#     """
#     Plot battery state of charge (SOC) as a bar plot in separate columns (phases),
#     with each node color-coded in a vibrant discrete palette.
#     """
#     data = []
#     for (time, node, phase), value in modelVals["B"].items():
#         data.append({
#             "time": time,
#             "node": str(node),
#             "phase": str(phase),
#             "value": value
#         })
#
#     fig = px.bar(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",
#         title="Battery State of Charge",
#         labels={"value": "State of Charge (%)", "time": "Time"},
#         height=400,
#         barmode="group",
#         color_discrete_sequence=px.colors.qualitative.Set1
#     )
#     fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)
#
#     save_plot(fig, "battery_soc.html")
#     fig.show()
#
# def plot_voltage(modelVals):
#     """
#     Plot voltage for each node as a line plot. Each node is represented by a unique color,
#     and the legend allows toggling individual nodes on/off.
#     """
#     data = []
#     for (time, node, phase), value in modelVals["v"].items():
#         data.append({
#             "time": time,
#             "node": str(node),  # Convert to string for discrete legend
#             "phase": str(phase),
#             "value": value
#         })
#
#     # Create a line plot with Plotly Express
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="node",        # Each node gets a distinct line/color
#         facet_col="phase",   # Separate columns for each phase
#         title="Voltage for Nodes",
#         labels={"value": "Voltage (p.u.)", "time": "Time"},
#         height=400,
#         color_discrete_sequence=px.colors.qualitative.Set1  # Use vibrant colors
#     )
#
#
#     # Show the plot
#     save_plot(fig, "voltage_plot.html")
#     fig.show()
#

## Plots to take any number of dictionaries as arguments and plot accordingly
import plotly.express as px
import plotly.graph_objects as go
import os

###############################################################################
# Helper Functions
###############################################################################

def save_plot(fig, filename):
    """
    Save the figure (HTML) to the same directory as this script.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    fig.write_html(filepath)

def combine_scenarios_into_one_legend(fig):
    """
    Merge all traces for a given dimension value (e.g. 'node=1') into a single
    legend entry labeled with all scenario names. For example, if Plotly has:
        "node=1, scenario=Scenario 1"
        "node=1, scenario=Scenario 2"
    we rename the first trace's legend entry to:
        "node=1 (Scenario 1, Scenario 2)"
    and hide the legend for the others.

    So you get exactly ONE legend item for 'node=1', listing the scenario names
    in parentheses. Double-clicking that item toggles all scenario lines/bars
    for node=1 at once.
    """
    # 1) Gather scenario sets for each dimension value
    dim_to_scenarios = {}
    for trace in fig.data:
        parts = trace.name.split(", scenario=")
        if len(parts) == 2:
            dim_value = parts[0]     # e.g. "node=1"
            sc_label = parts[1]     # e.g. "Scenario 1"
            if dim_value not in dim_to_scenarios:
                dim_to_scenarios[dim_value] = set()
            dim_to_scenarios[dim_value].add(sc_label)

    # 2) Build final legend labels: "node=1" -> "node=1 (Scenario 1, Scenario 2)"
    dim_to_combined_label = {}
    for dim_value, sc_set in dim_to_scenarios.items():
        sorted_scs = sorted(sc_set)
        sc_str = ", ".join(sorted_scs)
        dim_to_combined_label[dim_value] = f"{dim_value} ({sc_str})"

    # 3) Rename the *first* trace of each dimension to the combined label,
    #    hide the legend for the others.
    used_dims = set()
    for trace in fig.data:
        parts = trace.name.split(", scenario=")
        if len(parts) == 2:
            dim_value = parts[0]
            if dim_value not in used_dims:
                # first time => rename and show
                trace.name = dim_to_combined_label[dim_value]
                trace.showlegend = True
                trace.legendgroup = dim_value
                used_dims.add(dim_value)
            else:
                # subsequent => hide from legend, same legendgroup
                trace.showlegend = False
                trace.legendgroup = dim_value

    fig.update_layout(
        legend_groupclick="toggleitem",
        legend_title_text=""  # remove the default "node, scenario" title
    )

def _auto_scenario_labels(num):
    """Generate scenario labels: 'Scenario 1', 'Scenario 2', etc."""
    return [f"Scenario {i+1}" for i in range(num)]


###############################################################################
# 1) plot_substation_power
###############################################################################
def plot_substation_power(*modelVals_list):
    """
    Usage:
      plot_substation_power(modelvals)
      plot_substation_power(modelvals, OpendssVals, ...)
    Expects each dictionary to have:
      modelVals["P_subs"] : dict with (time, phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, phase), val in mv["P_subs"].items():
            data.append({
                "time": time,
                "phase": f"phase={phase}",
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.bar(
            data, x="time", y="value",
            color="phase", facet_col="phase",
            title="Substation Power"
        )
        fig.update_traces(marker_line_width=0, marker_line_color='black')
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="phase", pattern_shape="scenario",
            title="Substation Power (All Scenarios)",
            barmode="group"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "P_subs.html")
    fig.show()


###############################################################################
# 2) plot_battery_soc
###############################################################################
def plot_battery_soc(*modelVals_list):
    """
    Usage:
      plot_battery_soc(modelvals)
      plot_battery_soc(modelvals, OpendssVals, ...)
    Expects:
      modelVals["B"] : dict with (time, node, phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, node, phase), val in mv["B"].items():
            data.append({
                "time": time,
                "node": f"node={node}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="Battery State of Charge",
            barmode="group"
        )
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            pattern_shape="scenario",
            title="Battery State of Charge (All Scenarios)",
            barmode="group"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "battery_soc.html")
    fig.show()


###############################################################################
# 3) plot_reactive_power_flows
###############################################################################
def plot_reactive_power_flows(*modelVals_list):
    """
    Usage:
      plot_reactive_power_flows(modelvals, OpendssVals, ...)
    Expects:
      modelVals["Q"] : dict with (time, (fb,tb), phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, (fb, tb), phase), val in mv["Q"].items():
            data.append({
                "time": time,
                "branch": f"branch={fb}->{tb}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.line(
            data, x="time", y="value",
            color="branch", facet_col="phase",
            title="Reactive Power Flows"
        )
    else:
        fig = px.line(
            data, x="time", y="value",
            color="branch", line_dash="scenario",
            facet_col="phase",
            title="Reactive Power Flows (All Scenarios)"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "reactive_power_flows.html")
    fig.show()


###############################################################################
# 4) plot_der_reactive_power
###############################################################################
def plot_der_reactive_power(*modelVals_list):
    """
    Usage:
      plot_der_reactive_power(modelvals, OpendssVals, ...)
    Expects:
      modelVals["q_D"] : dict with (time, node, phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, node, phase), val in mv["q_D"].items():
            data.append({
                "time": time,
                "node": f"node={node}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="DER Reactive Power",
            barmode="group"
        )
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            pattern_shape="scenario",
            title="DER Reactive Power (All Scenarios)",
            barmode="group"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "DER_reactive_power.html")
    fig.show()


###############################################################################
# 5) plot_battery_charging_discharging_combined
###############################################################################
def plot_battery_charging_discharging_combined(*modelVals_list):
    """
    Usage:
      plot_battery_charging_discharging_combined(modelvals, OpendssVals, ...)

    Expects:
      modelVals["P_c"]: (time, node, phase) -> value (charging)
      modelVals["P_d"]: (time, node, phase) -> value (discharging)
    We'll store charging as negative, discharging as positive.
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, node, phase), val in mv["P_c"].items():
            data.append({
                "time": time,
                "node": f"node={node}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": -val,   # negative for charging
                "type": "Charging"
            })
        for (time, node, phase), val in mv["P_d"].items():
            data.append({
                "time": time,
                "node": f"node={node}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val,
                "type": "Discharging"
            })

    if len(modelVals_list) == 1:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="Battery Charging & Discharging",
            barmode="relative"
        )
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            pattern_shape="scenario",
            title="Battery Charging & Discharging (All Scenarios)",
            barmode="relative"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "Battery_Charging_Discharging_Combined.html")
    fig.show()


###############################################################################
# 6) plot_active_power_flows
###############################################################################
def plot_active_power_flows(*modelVals_list):
    """
    Usage:
      plot_active_power_flows(modelvals, OpendssVals, ...)
    Expects:
      modelVals["P"] : dict with (time, (fb, tb), phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, (fb, tb), phase), val in mv["P"].items():
            data.append({
                "time": time,
                "branch": f"branch={fb}->{tb}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.line(
            data, x="time", y="value",
            color="branch", facet_col="phase",
            title="Active Power Flows"
        )
    else:
        fig = px.line(
            data, x="time", y="value",
            color="branch", line_dash="scenario",
            facet_col="phase",
            title="Active Power Flows (All Scenarios)"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "active_power_flows.html")
    fig.show()


###############################################################################
# 7) plot_voltage
###############################################################################
def plot_voltage(*modelVals_list):
    """
    Usage:
      plot_voltage(modelvals, OpendssVals, ...)
    Expects:
      modelVals["v"] : dict with (time, node, phase) -> value
    """
    labels = _auto_scenario_labels(len(modelVals_list))
    data = []
    for mv, sc_label in zip(modelVals_list, labels):
        for (time, node, phase), val in mv["v"].items():
            data.append({
                "time": time,
                "node": f"node={node}",
                "phase": str(phase),
                "scenario": sc_label,
                "value": val
            })

    if len(modelVals_list) == 1:
        fig = px.line(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="Voltage for Nodes"
        )
    else:
        fig = px.line(
            data, x="time", y="value",
            color="node", line_dash="scenario",
            facet_col="phase",
            title="Voltage for Nodes (All Scenarios)"
        )
        combine_scenarios_into_one_legend(fig)

    save_plot(fig, "voltage_plot.html")
    fig.show()


