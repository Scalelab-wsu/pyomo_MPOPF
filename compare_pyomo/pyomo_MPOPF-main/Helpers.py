# Initialize an empty dictionary to store the final result
nested_dict = {}

# 1) Iterate over the key-value pairs in modelvals['v']
for (t, i, letter), val in modelvals['v'].items():
    if t not in nested_dict:
        nested_dict[t] = []  # Create an empty list for each unique t

    nested_dict[t].append({'idx': i, 'col': letter, 'val': val})

# 2) Convert lists to DataFrames for each t
for t, data in nested_dict.items():
    df = pd.DataFrame(data)
    df_pivot = df.pivot(index='idx', columns='col', values='val')
    # df_pivot = df_pivot.reindex(range(1, 126))  # Ensure consistent indexing
    df_pivot = df_pivot[['a', 'b', 'c']]  # Ensure consistent column order
    nested_dict[t] = df_pivot  # Replace list with pivoted DataFrame

# Display the result
for t, df in nested_dict.items():
    print(f"t = {t}:\n{df}\n")

# Initialize a result dictionary to store DataFrames for each time step
result = {}

# Collect all unique time steps
time_steps = set(t for (t, _, _) in modelvals['P'].keys())

# Process each time step
for t in time_steps:
    df_data = []

    # Iterate over (fb, tb) and phase in P and Q
    for (fb, tb, ph) in [(k[1][0], k[1][1], k[2]) for k in modelvals['P'].keys() if k[0] == t]:
        P_val = modelvals['P'].get((t, (fb, tb), ph), 0)
        Q_val = modelvals['Q'].get((t, (fb, tb), ph), 0)
        complex_val = complex(P_val, Q_val)  # Combine P and Q into P + jQ
        df_data.append({'fb': fb, 'tb': tb, 'ph': ph, 'val': complex_val})

    # Create a DataFrame from the collected data
    df = pd.DataFrame(df_data)

    # Pivot the DataFrame so that phases ('a', 'b', 'c') are columns
    df_pivot = df.pivot(index=['fb', 'tb'], columns='ph', values='val')

    # Reset index to make 'fb' and 'tb' regular columns
    df_pivot = df_pivot.reset_index()

    # Ensure consistent column order
    df_pivot = df_pivot[['fb', 'tb', 'a', 'b', 'c']]

    # Store the DataFrame in the result dictionary
    result[t] = df_pivot

# Display the result
for t, df in result.items():
    print(f"t = {t}:\n{df}\n")

# def update_area_values(area_info,data_by_area,p_global,q_global,v_global):
#     for area in area_info.keys():
#         for idx, conn_area in enumerate(area_info[area]['down_areas']):
#             local_node_id = area_info[area]['down_local_node_id'][idx]
#             for t in data_by_area[area]['Tset']:
#                 for ph in "abc":
#                     data_by_area[area]['p_L'][t,local_node_id,ph] = p_global[f"{conn_area}_{area}_p"][t-1]["abc".index(ph)]
#                     data_by_area[area]['q_L'][t,local_node_id,ph] = q_global[f"{conn_area}_{area}_q"][t-1]["abc".index(ph)]
#                     data_by_area[conn_area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t-1]["abc".index(ph)]
#                     # data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]
#
#         for idx, conn_area in enumerate(area_info[area]['up_area']):
#             local_node_id = area_info[area]['up_local_node_id'][idx]
#             for t in data_by_area[area]['Tset']:
#                 for ph in "abc":
#                     data_by_area[area]['p_L'][t, local_node_id, ph] = p_global[f"{conn_area}_{area}_p"][t - 1]["abc".index(ph)]
#                     data_by_area[area]['q_L'][t, local_node_id, ph] = q_global[f"{conn_area}_{area}_q"][t - 1]["abc".index(ph)]
#                     data_by_area[area]['v_swing'][t,local_node_id, ph] = v_global[f"{conn_area}_{area}_v"][t - 1]["abc".index(ph)]
#
#     return data_by_area