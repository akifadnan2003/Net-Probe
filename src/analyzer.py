"""
NetProbe – Performance Analyzer

Reads experiment results (list of metrics dicts) and produces:
  • per-experiment summary table (CSV)
  • 4-panel matplotlib figure (Throughput / Goodput / Retrans rate / Completion time)

Usage (from experiments.py):
    from analyzer import plot_experiment, save_summary_csv

Standalone usage:
    python analyzer.py --results results/summary.csv
"""

import csv
import os
import argparse
import ast

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False
    print('[ANALYZER] matplotlib not installed – plots disabled.')


# ── CSV summary ───────────────────────────────────────────────────────────────

def save_summary_csv(results: list, path: str):
    """Write a list of metric dicts to a CSV file."""
    if not results:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    keys = list(results[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(results)
    print(f'[ANALYZER] Summary CSV → {path}')


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_experiment(results: list,
                    x_label: str,
                    x_values: list,
                    title: str,
                    output_dir: str = 'results'):
    """
    4-panel figure saved as PNG.

    Args:
        results   : list of metric dicts (one per scenario point)
        x_label   : axis label for the independent variable
        x_values  : values for the x-axis (same length as results)
        title     : figure super-title
        output_dir: where to save the PNG
    """
    os.makedirs(output_dir, exist_ok=True)

    throughputs  = [r.get('throughput', 0) / 1024  for r in results]  # KB/s
    goodputs     = [r.get('goodput',    0) / 1024  for r in results]
    retrans_pct  = [r.get('retrans_rate', 0) * 100 for r in results]
    durations    = [r.get('duration', 0)            for r in results]

    if not MATPLOTLIB_OK:
        print('[ANALYZER] Skipping plot (matplotlib missing).')
        return None

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(title, fontsize=14, fontweight='bold')

    def _plot(ax, y, ylabel, color, ylim_zero=True):
        ax.plot(x_values, y, marker='o', color=color, linewidth=2)
        ax.set_xlabel(x_label, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.5)
        if ylim_zero:
            ax.set_ylim(bottom=0)

    _plot(axes[0, 0], throughputs, 'Throughput (KB/s)',      'steelblue')
    _plot(axes[0, 1], goodputs,    'Goodput (KB/s)',          'seagreen')
    _plot(axes[1, 0], retrans_pct, 'Retransmission Rate (%)', 'firebrick')
    _plot(axes[1, 1], durations,   'Completion Time (s)',     'darkorange')

    axes[0, 0].set_title('Throughput')
    axes[0, 1].set_title('Goodput')
    axes[1, 0].set_title('Retransmission Rate')
    axes[1, 1].set_title('Completion Time')

    plt.tight_layout()

    safe_title = title.replace(' ', '_').replace('/', '-')[:60]
    png_path   = os.path.join(output_dir, f'{safe_title}.png')
    plt.savefig(png_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[ANALYZER] Plot → {png_path}')
    return png_path


def plot_combined(all_experiments: dict, output_dir: str = 'results'):
    """
    Bar-chart summary across all experiments.
    all_experiments: {experiment_name: list_of_results}
    """
    if not MATPLOTLIB_OK:
        return
    os.makedirs(output_dir, exist_ok=True)

    names      = list(all_experiments.keys())
    avg_goodput = []
    avg_retrans = []

    for name, results in all_experiments.items():
        gp  = [r.get('goodput', 0) / 1024 for r in results]
        rr  = [r.get('retrans_rate', 0) * 100 for r in results]
        avg_goodput.append(sum(gp) / len(gp) if gp else 0)
        avg_retrans.append(sum(rr) / len(rr) if rr else 0)

    x = range(len(names))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle('NetProbe – Experiment Comparison', fontsize=13, fontweight='bold')

    ax1.bar(x, avg_goodput, color='seagreen', width=0.5)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(names, rotation=15, ha='right', fontsize=9)
    ax1.set_ylabel('Avg Goodput (KB/s)')
    ax1.set_title('Average Goodput per Experiment')
    ax1.set_ylim(bottom=0)
    ax1.grid(axis='y', linestyle='--', alpha=0.5)

    ax2.bar(x, avg_retrans, color='firebrick', width=0.5)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(names, rotation=15, ha='right', fontsize=9)
    ax2.set_ylabel('Avg Retransmission Rate (%)')
    ax2.set_title('Average Retransmission Rate per Experiment')
    ax2.set_ylim(bottom=0)
    ax2.grid(axis='y', linestyle='--', alpha=0.5)

    plt.tight_layout()
    out = os.path.join(output_dir, 'combined_summary.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[ANALYZER] Combined plot → {out}')
    return out


# ── Read metrics from client log CSV ─────────────────────────────────────────

def metrics_from_log(path: str) -> dict:
    """Parse a client_log.csv and extract the TRANSFER_COMPLETE row metrics."""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for row in reversed(rows):
        if row.get('event') == 'TRANSFER_COMPLETE':
            d = ast.literal_eval(row['details'])
            return {k: float(v) if _is_float(v) else v for k, v in d.items()}
    return {}


def _is_float(s):
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ── CLI standalone ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe Analyzer')
    p.add_argument('--results', required=True, help='results/summary.csv path')
    args = p.parse_args()

    with open(args.results, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows   = list(reader)

    for row in rows:
        print(row)
