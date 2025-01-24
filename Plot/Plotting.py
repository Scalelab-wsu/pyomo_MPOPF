

## Plots to take any number of dictionaries as arguments and plot accordingly
import plotly.express as px
import os
import matplotlib.pyplot as plt

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

import os

def save_png(fig, filename):
    """
    Save the figure (PNG or other formats) to the same directory as this script.

    Parameters:
    fig: Matplotlib figure to save.
    filename: Filename to save the figure.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    fig.savefig(filepath, dpi=300, format='png')


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
    fig.update_traces(marker_pattern_fillmode='overlay')
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
        fig.update_traces(marker_line_width=0, marker_line_color='black')
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="Battery State of Charge (All Scenarios)",
            pattern_shape="scenario",
            barmode="group"
        )
        fig.update_traces(marker_line_width=0, marker_line_color='black')

    fig.update_traces(marker_pattern_fillmode='overlay')
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
        fig.update_traces(marker_line_width=0, marker_line_color='black')
    else:
        fig = px.bar(
            data, x="time", y="value",
            color="node", facet_col="phase",
            title="DER Reactive Power (All Scenarios)",
            pattern_shape="scenario",
            barmode="group"
        )
        fig.update_traces(marker_line_width=0, marker_line_color='black')
    fig.update_traces(marker_pattern_fillmode='overlay')
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

    save_plot(fig, "voltage_plot.html")
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

