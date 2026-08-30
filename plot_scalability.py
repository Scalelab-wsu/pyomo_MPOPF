"""Generate the scalability summary figure (time + iterations vs P).

Reads pre-computed pkl files from run_logs/ and writes:
    Plot/scalability_summary.pdf

Usage:
    python plot_scalability.py                   # default: both systems, all P
    python plot_scalability.py --time-unit min   # y-axis in minutes (9500 is large)
"""
import os
import argparse
import matplotlib
matplotlib.use('Agg')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-logs', default='run_logs',
                        help='Directory containing dddp_*.pkl files')
    parser.add_argument('--out', default='Plot/scalability_summary.pdf',
                        help='Output path (pdf/png/svg)')
    parser.add_argument('--time-unit', choices=['s', 'min'], default='s',
                        help="Time axis unit: 's' (seconds) or 'min' (minutes)")
    parser.add_argument('--partitions', nargs='+', type=int, default=None,
                        help='Explicit P list, e.g. --partitions 2 3 4 6 8 12')
    args = parser.parse_args()

    wd       = os.path.dirname(os.path.abspath(__file__))
    run_logs = os.path.join(wd, args.run_logs)
    out_path = args.out if os.path.isabs(args.out) \
               else os.path.join(wd, args.out)

    from Plot.Plotting import plot_scalability_summary
    plot_scalability_summary(
        run_logs_dir   = run_logs,
        systems        = ('IEEE_123', 'IEEE_9500'),
        system_labels  = ('IEEE 123-bus', 'IEEE 9500-bus'),
        partition_list = args.partitions,
        out_path       = out_path,
        time_unit      = args.time_unit,
    )


if __name__ == '__main__':
    main()
