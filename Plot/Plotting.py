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
#     Plot substation power in three columns for three phases.
#     """
#     data = []
#     for (time, phase), value in modelVals["P_subs"].items():
#         data.append({"time": time, "phase": phase, "value": value})
#
#     fig = px.bar(
#         data,
#         x="time",
#         y="value",
#         facet_col="phase",
#         title="Substation Power",
#         labels={"value": "Power (MW)", "time": "Time"},
#         height=400
#     )
#     save_plot(fig, "P_subs.html")
#     fig.show()
#
# def plot_active_power_flows(modelVals):
#     """
#     Plot active power flows for all branches and phases.
#     """
#     data = []
#     for (time, (fb, tb), phase), value in modelVals["P"].items():
#         data.append({"time": time, "branch": f"{fb}->{tb}", "phase": phase, "value": value})
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
#     Plot reactive power flows for all branches and phases.
#     """
#     data = []
#     for (time, (fb, tb), phase), value in modelVals["Q"].items():
#         data.append({"time": time, "branch": f"{fb}->{tb}", "phase": phase, "value": value})
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
#
# def plot_der_reactive_power(modelVals):
#     """
#     Plot DER reactive power in separate rows for nodes and three columns for phases.
#     """
#     data = []
#     for (time, node, phase), value in modelVals["q_D"].items():
#         data.append({"time": time, "node": node, "phase": phase, "value": value})
#
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",  # Separate columns for each phase
#         title="DER Reactive Power",
#         labels={"value": "Reactive Power (MVAR)", "time": "Time"},
#         height=600,  # Adjust height as needed
#     )
#     save_plot(fig, "DER_reactive_power.html")
#     fig.show()
#
#
#
# def plot_battery_charging_discharging_combined(modelVals):
#     """
#     Plot battery charging and discharging power in the same plot for three phases.
#     Charging bars face downward, and discharging bars face upward.
#     """
#     data = []
#
#     # Adding charging data (negative values for downward bars)
#     for (time, node, phase), value in modelVals["P_c"].items():
#         data.append({"time": time, "node": node, "phase": phase, "value": -value, "type": "Charging"})
#
#     # Adding discharging data (positive values for upward bars)
#     for (time, node, phase), value in modelVals["P_d"].items():
#         data.append({"time": time, "node": node, "phase": phase, "value": value, "type": "Discharging"})
#
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",  # Separate columns for each phase
#         title="Battery Charging and Discharging Power",
#         labels={"value": "Power (MW)", "time": "Time"},
#         height=400,
#     )
#
#     save_plot(fig, "Battery_Charging_Discharging_Combined.html")
#     fig.show()
#
# def plot_battery_soc(modelVals):
#     """
#     Plot battery state of charge (SOC) in three columns for three phases with separate lines for nodes.
#     """
#     data = []
#     for (time, node, phase), value in modelVals["B"].items():
#         data.append({"time": time, "node": node, "phase": phase, "value": value})
#
#     fig = px.line(
#         data,
#         x="time",
#         y="value",
#         color="node",
#         facet_col="phase",  # Separate columns for each phase
#         title="Battery State of Charge",
#         labels={"value": "State of Charge (%)", "time": "Time"},
#         height=400
#     )
#     save_plot(fig, "battery_soc.html")
#     fig.show()
#

## creating barplots
import plotly.graph_objects as go
import plotly.express as px
import os

def save_plot(fig, filename):
    """
    Save the plot to the directory where the script is located.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    fig.write_html(filepath)

def plot_substation_power(modelVals):
    """
    Plot substation power in separate columns (phases) using a bar plot
    with a distinct color per phase for easy toggling in the legend.
    """
    data = []
    for (time, phase), value in modelVals["P_subs"].items():
        # Convert phase to string for discrete color if necessary
        data.append({
            "time": time,
            "phase": str(phase),
            "value": value
        })

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="phase",  # color by phase
        facet_col="phase",
        title="Substation Power",
        labels={"value": "Power (MW)", "time": "Time"},
        height=400,
        color_discrete_sequence=px.colors.qualitative.Set1  # Vibrant colors
    )
    # Make bars fully opaque, add black outline
    fig.update_traces(opacity=1, marker_line_width=0, marker_line_color='black')

    save_plot(fig, "P_subs.html")
    fig.show()

def plot_active_power_flows(modelVals):
    """
    Plot active power flows for all branches and phases (line plot).
    Typically doesn't need the discrete bar color logic, so we leave it as is.
    """
    data = []
    for (time, (fb, tb), phase), value in modelVals["P"].items():
        data.append({
            "time": time,
            "branch": f"{fb}->{tb}",
            "phase": phase,
            "value": value
        })

    fig = px.line(
        data,
        x="time",
        y="value",
        color="branch",
        facet_col="phase",
        title="Active Power Flows",
        labels={"value": "Active Power (MW)", "time": "Time"},
        height=400
    )
    save_plot(fig, "active_power_flows.html")
    fig.show()

def plot_reactive_power_flows(modelVals):
    """
    Plot reactive power flows for all branches and phases (line plot).
    Typically doesn't need the discrete bar color logic, so we leave it as is.
    """
    data = []
    for (time, (fb, tb), phase), value in modelVals["Q"].items():
        data.append({
            "time": time,
            "branch": f"{fb}->{tb}",
            "phase": phase,
            "value": value
        })

    fig = px.line(
        data,
        x="time",
        y="value",
        color="branch",
        facet_col="phase",
        title="Reactive Power Flows",
        labels={"value": "Reactive Power (MVAR)", "time": "Time"},
        height=400
    )
    save_plot(fig, "reactive_power_flows.html")
    fig.show()

def plot_der_reactive_power(modelVals):
    """
    Plot DER reactive power as a bar plot in separate columns for phases,
    with each node color-coded using a vibrant discrete sequence.
    """
    data = []
    for (time, node, phase), value in modelVals["q_D"].items():
        data.append({
            "time": time,
            "node": str(node),  # Convert node to string for discrete color
            "phase": str(phase),
            "value": value
        })

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="node",
        facet_col="phase",
        title="DER Reactive Power",
        labels={"value": "Reactive Power (MVAR)", "time": "Time"},
        height=600,
        barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set1
    )
    fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)

    save_plot(fig, "DER_reactive_power.html")
    fig.show()

def plot_battery_charging_discharging_combined(modelVals):
    """
    Plot battery charging (negative bar) & discharging (positive bar) in separate
    columns (phases), with each node color-coded in a vibrant discrete palette.
    """
    data = []
    # Charging data (negative)
    for (time, node, phase), value in modelVals["P_c"].items():
        data.append({
            "time": time,
            "node": str(node),
            "phase": str(phase),
            "value": -value,
            "type": "Charging"
        })

    # Discharging data (positive)
    for (time, node, phase), value in modelVals["P_d"].items():
        data.append({
            "time": time,
            "node": str(node),
            "phase": str(phase),
            "value": value,
            "type": "Discharging"
        })

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="node",
        facet_col="phase",
        title="Battery Charging and Discharging Power",
        labels={"value": "Power (MW)", "time": "Time"},
        height=400,
        color_discrete_sequence=px.colors.qualitative.Set1
    )

    # 'relative' mode so negative bars go below axis, positive above
    fig.update_layout(barmode='relative')
    fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)

    save_plot(fig, "Battery_Charging_Discharging_Combined.html")
    fig.show()

def plot_battery_soc(modelVals):
    """
    Plot battery state of charge (SOC) as a bar plot in separate columns (phases),
    with each node color-coded in a vibrant discrete palette.
    """
    data = []
    for (time, node, phase), value in modelVals["B"].items():
        data.append({
            "time": time,
            "node": str(node),
            "phase": str(phase),
            "value": value
        })

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="node",
        facet_col="phase",
        title="Battery State of Charge",
        labels={"value": "State of Charge (%)", "time": "Time"},
        height=400,
        barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set1
    )
    fig.update_traces(opacity=1, marker_line_width=0, width = 0.8)

    save_plot(fig, "battery_soc.html")
    fig.show()

