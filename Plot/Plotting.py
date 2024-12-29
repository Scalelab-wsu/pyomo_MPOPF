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
    Plot substation power in three columns for three phases.
    """
    data = []
    for (time, phase), value in modelVals["P_subs"].items():
        data.append({"time": time, "phase": phase, "value": value})

    fig = px.bar(
        data,
        x="time",
        y="value",
        facet_col="phase",
        title="Substation Power",
        labels={"value": "Power (MW)", "time": "Time"},
        height=400
    )
    save_plot(fig, "P_subs.html")

def plot_active_power_flows(modelVals):
    """
    Plot active power flows for all branches and phases.
    """
    data = []
    for (time, (fb, tb), phase), value in modelVals["P"].items():
        data.append({"time": time, "branch": f"{fb}->{tb}", "phase": phase, "value": value})

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

def plot_reactive_power_flows(modelVals):
    """
    Plot reactive power flows for all branches and phases.
    """
    data = []
    for (time, (fb, tb), phase), value in modelVals["Q"].items():
        data.append({"time": time, "branch": f"{fb}->{tb}", "phase": phase, "value": value})

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

def plot_der_reactive_power(modelVals):
    """
    Plot DER reactive power in three columns for three phases.
    """
    data = []
    for (time, node, phase), value in modelVals["q_D"].items():
        data.append({"time": time, "node": node, "phase": phase, "value": value})

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="node",
        facet_col="phase",
        title="DER Reactive Power",
        labels={"value": "Reactive Power (MVAR)", "time": "Time"},
        height=400
    )
    save_plot(fig, "DER_reactive_power.html")

def plot_battery_charging_discharging(modelVals):
    """
    Plot battery charging and discharging power in three columns for three phases.
    """
    for var_name, title in zip(["P_c", "P_d"], ["Battery Charging Power", "Battery Discharging Power"]):
        data = []
        for (time, node, phase), value in modelVals[var_name].items():
            data.append({"time": time, "node": node, "phase": phase, "value": value})

        fig = px.bar(
            data,
            x="time",
            y="value",
            color="node",
            facet_col="phase",
            title=title,
            labels={"value": "Power (MW)", "time": "Time"},
            height=400
        )
        save_plot(fig, f"{title.replace(' ', '_')}.html")

def plot_battery_soc(modelVals):
    """
    Plot battery state of charge (SOC) in three columns for three phases.
    """
    data = []
    for (time, node, phase), value in modelVals["B"].items():
        data.append({"time": time, "node": node, "phase": phase, "value": value})

    fig = px.bar(
        data,
        x="time",
        y="value",
        color="node",
        facet_col="phase",
        title="Battery State of Charge",
        labels={"value": "State of Charge (%)", "time": "Time"},
        height=400
    )
    save_plot(fig, "battery_soc.html")
