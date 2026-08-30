import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dssconverter.dssparser import DSSParser
from pathlib import Path
# Always resolve paths relative to project root, regardless of cwd
wd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def savedsscsv(
    dssparser: DSSParser, folderpath: str = None, overwrite: bool = True
) -> None:
    if folderpath is None:
        # folderpath = os.path.join(wd, "rawData", "IEEE_123", "csvs")
        folderpath = os.path.join(wd, "rawData", "IEEE_8500", "csvs")
        # folderpath = os.path.join(wd, "rawData", "IEEE_13", "csvs")
        Path(folderpath).mkdir(parents=True, exist_ok=overwrite)
    else:
        folderpath = os.path.abspath(folderpath)

    dssparser.branch_data.to_csv(f"{folderpath}/branch_data.csv", index=False)
    dssparser.bus_data.to_csv(f"{folderpath}/bus_data.csv", index=False)
    dssparser.cap_data.to_csv(f"{folderpath}/cap_data.csv", index=False)
    dssparser.gen_data.to_csv(f"{folderpath}/gen_data.csv", index=False)
    dssparser.reg_data.to_csv(f"{folderpath}/reg_data.csv", index=False)
    dssparser.bat_data.to_csv(f"{folderpath}/battery_data.csv", index=False)

def main() -> None:
    # master_path = os.path.join(wd, "rawData", "IEEE_123", "dss_scripts", "Master.dss")
    master_path = os.path.join(wd, "rawData", "IEEE_8500", "dss_scripts", "Master.dss")
    # master_path = os.path.join(wd, "..", "rawData", "IEEE_13", "dss_scripts", "Master.dss")
    dss_data = DSSParser(master_path)
    savedsscsv(dss_data)
    print("DSS data successfully saved to CSV files.")

if __name__ == "__main__":
    main()
