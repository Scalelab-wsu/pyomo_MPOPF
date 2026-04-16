import pandas as pd

# Create a sample DataFrame with unsorted 'time' and 'node' values
data = {
    "time": [3, 1, 2, 1, 3, 2],
    "node": [2, 1, 2, 2, 1, 1],
    "value": [10, 20, 30, 40, 50, 60]
}

df = pd.DataFrame(data)
print("Before sorting:")
print(df)

# Sort the DataFrame first by 'time' then by 'node'
df = df.sort_values(by=["time", "node"])
print("\nAfter sorting:")
print(df)
