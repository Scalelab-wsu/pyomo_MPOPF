from pathlib import Path
import numpy as np
import pandas as pd
import opendssdirect as dss

# %%
PROJECT_ROOT = Path(r"D:\Documents\pyomo_MPOPF")  # hard-set once
# system_name = 'IEEE_13'
system_name = 'IEEE_123_other'
# system_name = 'IEEE_9500'
filepath = PROJECT_ROOT / "rawData" / system_name / "csvs"
dss_path = PROJECT_ROOT / "rawData" / system_name / "dss_scripts" / "Master.dss"
MASTER = dss_path

dss.Basic.ClearAll()
dss.Text.Command(f'compile "{MASTER}"')

dss.Lines.First()
first_line_name = dss.Lines.Name()  # full DSS object name is safest
freeze_controls = True

if freeze_controls:
    dss.Text.Command("Set ControlMode=Off")

dss.Text.Command("Solve mode=snap")

print("Solved base case.")

# Open from terminal 1 (most common). If you need terminal 2, change term=2.
dss.Text.Command(f"Open Line.{first_line_name} term=1")

# Re-solve
dss.Text.Command("Solve mode=snap")

print(f"Opened Line.{first_line_name} at term=1 and re-solved.")

dss.Circuit.SetActiveElement(first_line_name)

I = np.array(dss.CktElement.Currents())
I_complex = I[0::2] + 1j * I[1::2]

print("Bus names:", dss.CktElement.BusNames())
print("Max |I| after open (A):", np.max(np.abs(I_complex)))

# Also check total power through the element (kW, kvar) at each terminal (OpenDSS convention)
Powers = np.array(dss.CktElement.Powers())  # [P1,Q1,P2,Q2,...] in kW/kvar
print("Element terminal powers (kW/kvar pairs):", Powers.reshape(-1, 2))
# %%
# 2. Set the active bus where you want the Thevenin impedance
# This is typically the bus where the Vsource is connected, e.g., "SourceBus"
dss.Text.Command("solve mode=fault")
dss.Vsources.First()
target_bus = dss.CktElement.BusNames()[0].split('.')[0]  # Replace with your actual bus name
dss.Text.Command(f'Set Bus={target_bus}')

# 3. Use the ZscMatrix command to get the short circuit impedance matrix
# Note: This is the full Z matrix (complex numbers) for the active bus
# The result needs to be converted to a NumPy array for easier manipulation if using opendssdirect
zsc = dss.Bus.ZscMatrix()  # This returns a flattened array of complex numbers

print(zsc)

# %%

kv = dss.Bus.kVBase()
print(kv)

# t_ratio = (kv*kv)/(66.39*66.39)  # Convert to ohms
t_ratio = 1

print(t_ratio)
# Convert to a square matrix
num_phases = dss.Bus.NumNodes()
print(num_phases)

Raa = zsc[0] * t_ratio
Xaa = zsc[1] * t_ratio
Rab = zsc[2] * t_ratio
Xab = zsc[3] * t_ratio
Rac = zsc[4] * t_ratio
Xac = zsc[5] * t_ratio
Rba = zsc[6] * t_ratio
Xba = zsc[7] * t_ratio
Rbb = zsc[8] * t_ratio
Xbb = zsc[9] * t_ratio
Rbc = zsc[10] * t_ratio
Xbc = zsc[11] * t_ratio
Rca = zsc[12] * t_ratio
Xca = zsc[13] * t_ratio
Rcb = zsc[14] * t_ratio
Xcb = zsc[15] * t_ratio
Rcc = zsc[16] * t_ratio
Xcc = zsc[17] * t_ratio

R_matrix = np.array([[Raa, Rab, Rac],
                     [Rba, Rbb, Rbc],
                     [Rca, Rcb, Rcc]])
X_matrix = np.array([[Xaa, Xab, Xac],
                     [Xba, Xbb, Xbc],
                     [Xca, Xcb, Xcc]])

print(R_matrix)

print(X_matrix)

# %%
MASTER = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Master_ckt5.dss"

dss.Basic.ClearAll()
dss.Text.Command(f'compile "{MASTER}"')
dss.Text.Command("solve")
# %%
lines = dss.utils.lines_to_dataframe()
loads = dss.utils.loads_to_dataframe()
# lines=lines[['Name','Bus1','Bus2','RMatrix','XMatrix','CMatrix']]
transformers = dss.utils.transformers_to_dataframe()
dss.Solution.Solve()
bus_names = []
powers = []

# %%
for t in dss.Transformers.AllNames():
    dss.Circuit.SetActiveElement("transformer." + t)
    # print(dss.CktElement.Name())
    # print(dss.CktElement.BusNames())
    if dss.CktElement.Enabled == False:
        break
    else:
        bus_names.append(dss.CktElement.BusNames())
        powers.append(dss.CktElement.Powers())
transformer_powers = pd.DataFrame({'Bus_Names': bus_names, 'Powers_kW_kvar': powers})
save_path = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Transformer_Powers.csv"
transformer_powers.to_csv(save_path, index=False)
print(f"Saved transformer powers to {save_path}")
# %%
print(powers)
# %%
rec = []
import cmath

for t in dss.Transformers.AllNames():
    dss.Circuit.SetActiveElement("transformer." + t)
    y = dss.Transformers.IsDelta()
    # if y==True:
    #     print(y)
    if dss.CktElement.NumPhases() == 1:
        name = dss.CktElement.Name().split(".")[1]
        phase = dss.CktElement.NumPhases()
        primary_bus = dss.CktElement.BusNames()[0]
        dss.Circuit.SetActiveBus(primary_bus)
        kv = dss.Bus.kVBase()
        a, b = dss.CktElement.Powers()[:2]  # this is complex
        print(a, b)
        # z=complex(a,b)
        kw = a
        kvar = b
        rec.append([name, phase, primary_bus, kv, kw, kvar])

print("All transformers:")
for item in rec:
    print(item)

save_path = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Transformer_Powers_SubReg.csv"
transformer_powers_subreg = pd.DataFrame(rec, columns=['Name', 'Phases', 'Primary_Bus', 'kV', 'kW', 'kvar'])
transformer_powers_subreg.to_csv(save_path, index=False)
print(f"Saved substation and regulator transformer powers to {save_path}")

# Keeping substation transformer and regulator transformers
# rec=rec[3:]
# rec=rec[:-9]

# %%
s = str()
for i in rec:
    #   bus_name = i[2].split('.')[1]
    s += "New load." + i[0] + "  " + "phases=" + str(i[1]) + "  " + "Bus=" + i[2] + "  " + "kv=" + str(
        i[3]) + "  " + "conn=wye" + "  " + "kw=" + str(i[4]) + "  " + "kvar=" + str(i[5]) + "\n"

with open("Loads_ckt5_reduced.dss", 'w') as file:
    file.write(s)
# %%
# Copy Master_ckt5.dss and modify it
src = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Master_ckt5.dss"
dst = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Master_ckt5_reduced.dss"

with open(src, 'r') as f:
    content = f.read()

# Replace the line
content = content.replace('Redirect  Loads_ckt5.dss', '//Redirect  Loads_ckt5.dss\nRedirect  Loads_ckt5_reduced.dss')

with open(dst, 'w') as f:
    f.write(content)

print(f"Created {dst}")
# %%
MASTERNew = "/Users/anamikadubey/code/opendss-vscode/electricdss-tst/Version8/Distrib/EPRITestCircuits/ckt5/Master_ckt5_reduced.dss"

dss.Basic.ClearAll()

dss.Text.Command(f'compile "{MASTERNew}"')

dss.Text.Command("solve")

Lineinf = []
idx = dss.Lines.First()

bus_names = dss.Circuit.AllBusNames()
bus_distances = dss.Circuit.AllBusDistances()

df = pd.DataFrame({
    'Bus Name': bus_names,
    'Distance (km)': bus_distances
})

# Export to a CSV file
export_filename = 'BusDistances.csv'
df.to_csv(export_filename, index=False)
# %%
while idx > 0:
    # Activate the line element
    # name = dss.CktElement.Name().split(".")[1]
    name = dss.Lines.Name()
    # print(name)
    is_switch = dss.Lines.IsSwitch
    from_bus = dss.Lines.Bus1().split(".")[0]
    to_bus = dss.Lines.Bus2().split(".")[0]
    n = dss.Lines.Phases()
    norm = dss.Lines.NormAmps()
    emerg = dss.Lines.EmergAmps()
    r = np.array(dss.Lines.RMatrix())
    r = r.reshape(n, n)
    x = np.array(dss.Lines.XMatrix())
    x = x.reshape(n, n)
    c = np.array(dss.Lines.CMatrix())
    c = c.reshape(n, n)
    dss.Circuit.SetActiveElement("line." + name)
    phase = dss.CktElement.NodeOrder()[0:n]
    l = np.array(dss.Lines.Length())
    sw_imp = 0
    if (n == 3):
        Raa = r[0][0] * l
        Rab = r[0][1] * l
        Rac = r[0][2] * l
        Rbb = r[1][1] * l
        Rbc = r[1][2] * l
        Rcc = r[2][2] * l
        Xaa = x[0][0] * l
        Xab = x[0][1] * l
        Xac = x[0][2] * l
        Xbb = x[1][1] * l
        Xbc = x[1][2] * l
        Xcc = x[2][2] * l
    elif (n == 1):
        if 1 in phase:
            Raa = r[0] * l
            Rab = 0.0
            Rac = 0.0
            Rbb = 0.0
            Rbc = 0.0
            Rcc = 0.0
            Xaa = x[0] * l
            Xab = 0.0
            Xac = 0.0
            Xbb = 0.0
            Xbc = 0.0
            Xcc = 0.0
        if 2 in phase:
            Raa = 0.0
            Rab = 0.0
            Rac = 0.0
            Rbb = r[0] * l
            Rbc = 0.0
            Rcc = 0.0
            Xaa = 0.0
            Xab = 0.0
            Xac = 0.0
            Xbb = x[0] * l
            Xbc = 0.0
            Xcc = 0.0
        if 3 in phase:
            Raa = 0.0
            Rab = 0.0
            Rac = 0.0
            Rbb = 0.0
            Rbc = 0.0
            Rcc = r[0] * l
            Xaa = 0.0
            Xab = 0.0
            Xac = 0.0
            Xbb = 0.0
            Xbc = 0.0
            Xcc = x[0] * l
    elif (n == 2):
        if 1 in phase and 2 in phase:
            Raa = r[0][0] * l
            Rab = r[0][1] * l
            Rac = 0.0
            Rbb = r[1][1] * l
            Rbc = 0.0
            Rcc = 0.0
            Xaa = x[0][0] * l
            Xab = x[0][1] * l
            Xac = 0.0
            Xbb = x[1][1] * l
            Xbc = 0.0
            Xcc = 0.0
        if 2 in phase and 3 in phase:
            Raa = 0.0
            Rab = 0.0
            Rac = 0.0
            Rbb = r[0][0] * l
            Rbc = r[0][1] * l
            Rcc = r[1][1] * l
            Xaa = 0.0
            Xab = 0.0
            Xac = 0.0
            Xbb = x[0][0] * l
            Xbc = x[0][1] * l
            Xcc = x[1][1] * l
        if 1 in phase and 3 in phase:
            Raa = r[0][0] * l
            Rab = 0.0
            Rac = r[0][1] * l
            Rbb = 0.0
            Rbc = 0.0
            Rcc = r[1][1] * l
            Xaa = x[0][0] * l
            Xab = 0.0
            Xac = x[0][1] * l
            Xbb = 0.0
            Xbc = 0.0
            Xcc = x[1][1] * l
    if name == 'mdv201_connector':
        Raa = R_matrix[0][0]
        Rab = R_matrix[0][1]
        Rac = R_matrix[0][2]
        Rbb = R_matrix[1][1]
        Rbc = R_matrix[1][2]
        Rcc = R_matrix[2][2]
        Xaa = X_matrix[0][0]
        Xab = X_matrix[0][1]
        Xac = X_matrix[0][2]
        Xbb = X_matrix[1][1]
        Xbc = X_matrix[1][2]
        Xcc = X_matrix[2][2]

    Lineinf.append([from_bus, to_bus, Raa, Rab, Rac, Rbb, Rbc, Rcc, Xaa, Xab, Xac, Xbb, Xbc, Xcc, norm, emerg, name])

    idx = dss.Lines.Next()

Lineinf = pd.DataFrame(Lineinf)
Lineinf = Lineinf.to_numpy()

print(Lineinf[1, :])
# %%
import networkx as nx
from collections import deque

# Build graph from Lineinf
G = nx.Graph()
for row in Lineinf:
    G.add_edge(row[0], row[1])

num_components = nx.number_connected_components(G)
print(f"Number of connected components: {num_components}")
# %%
# Choose a root bus (e.g., first bus in Lineinf)
root_bus = Lineinf[0][0]

# BFS traversal to assign numbers
visited = set()
bus_to_number_bfs = {}
queue = deque([root_bus])
num = 1

while queue:
    bus = queue.popleft()
    if bus not in visited:
        bus_to_number_bfs[bus] = num
        num += 1
        visited.add(bus)
        # Add neighbors not yet visited
        for neighbor in G.neighbors(bus):
            if neighbor not in visited and neighbor not in queue:
                queue.append(neighbor)

# Assign numbers to any disconnected buses (not reached by BFS)
for row in Lineinf:
    for bus in [row[0], row[1]]:
        if bus not in bus_to_number_bfs:
            bus_to_number_bfs[bus] = num
            num += 1

print("BFS bus numbering (first 10):")
for bus, number in list(bus_to_number_bfs.items())[:10]:
    print(f"{bus} -> {number}")

# To create Lineinf_numbered with BFS order:
Lineinf_numbered_bfs = []
for row in Lineinf:
    from_bus_num = bus_to_number_bfs[row[0]]
    to_bus_num = bus_to_number_bfs[row[1]]
    new_row = [from_bus_num, to_bus_num] + list(row)
    Lineinf_numbered_bfs.append(new_row)
Lineinf_numbered_bfs = np.array(Lineinf_numbered_bfs, dtype=object)
# %%
# Save numbered Lineinf to a text file
# Format: from_bus_num to_bus_num from_bus to_bus Raa Rab Rac Rbb Rbc Rcc Xaa Xab Xac Xbb Xbc Xcc
header = "from_bus_num to_bus_num from_bus to_bus Raa Rab Rac Rbb Rbc Rcc Xaa Xab Xac Xbb Xbc Xcc norm emerg name\n"
with open("Lineinf_numbered_bfs.txt", 'w') as file:
    file.write(header)
    for line in Lineinf_numbered_bfs:
        # Convert all values to strings and join with spaces
        line_str = " ".join(str(x) for x in line)
        file.write(line_str + "\n")

print(f'Wrote Lineinf_numbered_bfs.txt with {len(Lineinf_numbered_bfs)} rows')

# %%
Loadinf = []
idx = dss.Loads.First()
# active class sets active cktelement


while idx > 0:
    name = dss.Loads.Name()
    dss.Circuit.SetActiveElement("load." + name)
    n = dss.CktElement.NumPhases()
    phases = dss.CktElement.NodeOrder()[0:n]
    bus_name = dss.CktElement.BusNames()[0].split(".")[0]

    if n == 2:
        print(n)
    if n == 3:
        print(n)
    #  print(dss.Loads.kW())
    #  print(dss.Loads.kvar())
    # Only consiering single phase loads 8500- Node feeder
    if 1 in phases:
        PLa = dss.Loads.kW()
        QLa = dss.Loads.kvar()
        PLb = 0.0
        QLb = 0.0
        PLc = 0.0
        QLc = 0.0
        PVa = 0.0
        PVb = 0.0
        PVc = 0.0

    elif 2 in phases:
        PLb = dss.Loads.kW()
        QLb = dss.Loads.kvar()
        PLc = 0.0
        QLc = 0.0
        PLa = 0.0
        QLa = 0.0
        PVa = 0.0
        PVb = 0.0
        PVc = 0.0

    elif 3 in phases:
        PLc = dss.Loads.kW()
        QLc = dss.Loads.kvar()
        PLa = 0.0
        QLa = 0.0
        PLb = 0.0
        QLb = 0.0
        PVa = 0.0
        PVb = 0.0
        PVc = 0.0

    Loadinf.append([bus_name, PLa, QLa, PLb, QLb, PLc, QLc, PVa, PVb, PVc])
    idx = dss.Loads.Next()

Loadinf = np.array(Loadinf)
# Loadinf


# %%
# Save Loadinf to a text file
# Format: name PLa QLa PLb QLb PLc QLc PVa PVb PVc
header = "name PLa QLa PLb QLb PLc QLc PVa PVb PVc\n"
with open("Loadinf.txt", 'w') as file:
    file.write(header)
    for row in Loadinf:
        # Ensure each element is string (handles mixed types)
        row_str = " ".join(str(x) for x in row)
        file.write(row_str + "\n")

print('Wrote Loadinf.txt with', len(Loadinf), 'rows')


# %%
# Map load bus names to existing bus numbers (from bus_to_number)
# Output: Loadinf_numbered with leading bus_num column

def _base_bus_name(bus: str) -> str:
    # Use everything before the first dot as the base bus name
    return str(bus).split('.')[0]


mapped = 0
missing = set()
Loadinf_numbered_bfs = []

for row in Loadinf:
    bus = str(row[0])
    # Try exact match first
    num = bus_to_number_bfs.get(bus)
    if num is None:
        # Fallback to base bus (before '.')
        num = bus_to_number_bfs.get(_base_bus_name(bus))
    if num is None:
        missing.add(bus)
        num = -1  # sentinel for unmatched
    else:
        mapped += 1
    Loadinf_numbered_bfs.append([num] + list(row))

Loadinf_numbered_bfs = np.array(Loadinf_numbered_bfs, dtype=object)

print(f"Mapped loads: {mapped} / {len(Loadinf)}")
if missing:
    print(f"Unmatched buses (showing up to 10): {list(sorted(missing))[:10]}")
else:
    print("All load buses matched to numbering.")

# %%
# Save Loadinf_numbered to a text file
# Format: bus_num name PLa QLa PLb QLb PLc QLc PVa PVb PVc
header = "bus_num name PLa QLa PLb QLb PLc QLc PVa PVb PVc\n"
with open("Loadinf_numbered_bfs.txt", 'w') as file:
    file.write(header)
    for row in Loadinf_numbered_bfs:
        row_str = " ".join(str(x) for x in row)
        file.write(row_str + "\n")

print(f"Wrote Loadinf_numbered_bfs.txt with {len(Loadinf_numbered_bfs)} rows")

# %%
# Collect mapping rows: [bus_name, bus_num, nph]
rows = []
for bus in G.nodes():
    bname = str(bus)
    # Map to BFS number (use base name fallback)
    num = bus_to_number_bfs.get(bname)
    if num is None:
        num = bus_to_number_bfs.get(bname.split('.')[0], -1)
    try:
        num = int(num)
    except Exception:
        num = -1

    # Determine number of phases (nodes) from OpenDSS
    nph = 0
    try:
        dss.Circuit.SetActiveBus(bname.split('.')[0])
        nph = int(dss.Bus.NumNodes())
        bus_dist = dss.Bus.Distance()
        if not nph:
            try:
                nodes = dss.Bus.Nodes()
                nph = len(nodes) if nodes is not None else 0
            except Exception:
                nph = 0
                bus_dist = 0
    except Exception:
        nph = 0
        bus_dist = 0

    rows.append([bname, num, nph, bus_dist])

# Sort by bus number ascending; place unmatched (-1) at the end
matched = [r for r in rows if r[1] != -1]
unmatched = [r for r in rows if r[1] == -1]
matched.sort(key=lambda r: (r[1], r[0]))
unmatched.sort(key=lambda r: r[0])
rows_sorted = matched + unmatched

# Create DataFrame
bus_bfs_df = pd.DataFrame(rows_sorted, columns=["bus_name", "bus_num", "nph", "bus_distance"])
print(f"Total buses in G: {len(bus_bfs_df)}")
print(bus_bfs_df.head(10).to_string(index=False))

# Save to files
txt_file = "bus_bfs_mapping.csv"
with open(txt_file, 'w') as f:
    f.write("bus_name,bus_num,nph,bus_distance\n")
    for bname, num, nph, bus_dist in rows_sorted:
        f.write(f"{bname},{num},{nph},{bus_dist}\n")
print(f"Saved mapping to {txt_file} (sorted by bus_num; includes nph)")
# %%
# Expand Loadinf_numbered_bfs to include all buses (zero-fill missing buses) and include number of phases (nph)
import numpy as np
import pandas as pd

# Expect: Loadinf_numbered_bfs (cols: bus_num, name, PLa, QLa, PLb, QLb, PLc, QLc, PVa, PVb, PVc)
#         bus_to_number_bfs dict is available

# Build inverse mapping num -> bus_name (base name)
number_to_bus = {int(num): str(bus).split('.')[0] for bus, num in bus_to_number_bfs.items()}


# Helper to get number of phases for a given bus base name
def get_bus_nph(bus_base: str) -> int:
    try:
        dss.Circuit.SetActiveBus(str(bus_base))
        nph = int(dss.Bus.NumNodes())
        if not nph:
            try:
                nodes = dss.Bus.Nodes()
                return len(nodes) if nodes is not None else 0
            except Exception:
                return 0
        return nph
    except Exception:
        return 0


# Precompute nph for all BFS-numbered buses
bus_phase_count = {}
for num, bname in number_to_bus.items():
    bus_phase_count[int(num)] = get_bus_nph(bname)

# Coerce Loadinf_numbered_bfs to numpy array of objects
arr = np.array(Loadinf_numbered_bfs, dtype=object)

# Split into matched (bus_num >=1) and unmatched (-1 or invalid)
matched_rows = []
unmatched_rows = []
for row in arr:
    try:
        bnum = int(row[0])
    except Exception:
        bnum = -1
    if bnum >= 1:
        matched_rows.append(row)
    else:
        unmatched_rows.append(row)

# Determine total buses and which are already present
total_buses = int(max(bus_to_number_bfs.values())) if bus_to_number_bfs else 0
present = set()
for r in matched_rows:
    try:
        present.add(int(r[0]))
    except Exception:
        pass

# Rebuild matched rows to include nph after name
matched_with_nph = []
for row in matched_rows:
    bnum = int(row[0])
    bname = str(row[1])
    nph = int(bus_phase_count.get(bnum, get_bus_nph(bname.split('.')[0])))
    matched_with_nph.append([bnum, bname, nph] + list(row[2:]))

# Create zero-load rows for missing bus numbers, including nph
zero_rows = []
for b in range(1, total_buses + 1):
    if b not in present:
        bname = number_to_bus.get(b, f"BUS_{b}")
        nph = int(bus_phase_count.get(b, get_bus_nph(bname)))
        zero_rows.append([b, bname, nph, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

# For unmatched rows (bus_num == -1), add nph computed from their bus name base
unmatched_with_nph = []
for row in unmatched_rows:
    bname = str(row[1])
    nph = get_bus_nph(bname.split('.')[0])
    unmatched_with_nph.append([row[0], bname, nph] + list(row[2:]))

# Combine and sort by bus number; append unmatched at the end
combined = np.array(matched_with_nph + zero_rows, dtype=object)
try:
    order = np.argsort(combined[:, 0].astype(int))
    combined = combined[order]
except Exception:
    pass

if unmatched_with_nph:
    combined = np.concatenate([combined, np.array(unmatched_with_nph, dtype=object)], axis=0)

# Save to files
header = "bus_num name nph PLa QLa PLb QLb PLc QLc PVa PVb PVc\n"
out_txt = "Loadinf_numbered_bfs_allbuses.txt"
with open(out_txt, 'w') as f:
    f.write(header)
    for row in combined:
        f.write(" ".join(str(x) for x in row) + "\n")

print(
    f"Expanded Loadinf rows: original={len(arr)}, matched={len(matched_rows)}, added_zero={len(zero_rows)}, unmatched_kept={len(unmatched_rows)}")
print(f"Saved {out_txt} (sorted by bus_num; includes nph)")