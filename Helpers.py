def check_simultaneous_charging_discharging(results, threshold=1e-7):
    """
    Checks the 'results' dictionary for any battery/time/phase tuple where
    both P_c and P_d are greater than 'threshold' simultaneously.
    Prints a warning message if such a case is found.
    """
    # Loop over all (t, j, ph) keys in P_c
    for (t, j, ph), p_c_val in results['P_c'].items():
        p_d_val = results['P_d'][(t, j, ph)]
        # Check if both exceed threshold
        if p_c_val > threshold and p_d_val > threshold:
            print(f"WARNING: Battery {j} at time {t}, phase {ph} is "
                  f"both charging ({p_c_val}) and discharging ({p_d_val}).")
