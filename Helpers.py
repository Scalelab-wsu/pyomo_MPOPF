def check_simultaneous_charging_discharging(results, threshold=5e-5):
    """
    Checks the 'results' dictionary for any battery/time/phase tuple where
    both P_c and P_d are greater than 'threshold' simultaneously.
    Prints a warning message if such a case is found.
    """
    # ANSI color codes
    RED = '\033[91m'
    GREEN = '\033[92m'
    RESET = '\033[0m'

    # Loop over all (t, j, ph) keys in P_c
    for (t, j), p_c_val in results['P_c'].items():
        p_d_val = results['P_d'][(t, j)]
        # Check if both exceed threshold
        if p_c_val > threshold and p_d_val > threshold:
            print(f"{RED}WARNING: Battery {j} at time {t},"
                  f"both charging ({p_c_val}) and discharging ({p_d_val}).{RESET}")
    else:
        print(f"{GREEN}No SCD detected{RESET}")
