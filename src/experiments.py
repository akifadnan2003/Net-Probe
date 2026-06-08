"""
NetProbe – Automated Experiment Runner

Runs the four required experiment scenarios and produces graphs + CSV summary.
Each scenario starts the server in a background thread, runs the client in the
foreground, then collects results.

Usage:
  python experiments.py

All output goes to:
  results/   – PNG graphs, summary CSV
  logs/      – per-run log files
"""

import os
import sys
import threading
import time
import random
import argparse

# ── test-file generation ──────────────────────────────────────────────────────

def _make_file(path: str, size_bytes: int):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        # deterministic pseudo-random bytes (reproducible across runs)
        rng = random.Random(42)
        block = 65536
        remaining = size_bytes
        while remaining > 0:
            n = min(block, remaining)
            f.write(bytes(rng.getrandbits(8) for _ in range(n)))
            remaining -= n
    print(f'[SETUP] Created test file: {path} ({size_bytes:,} bytes)')


# ── server helper ─────────────────────────────────────────────────────────────

def _start_server(port: int, loss_rate: float, log_path: str) -> threading.Thread:
    """Start server in a daemon thread; it handles ONE transfer then returns."""
    from server import serve_once

    result_box = [None]

    def _run():
        result_box[0] = serve_once(
            host='127.0.0.1', port=port,
            output_dir='received',
            loss_rate=loss_rate,
            log_path=log_path,
            idle_timeout=60,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.3)   # give server time to bind
    return t


# ── single experiment point ───────────────────────────────────────────────────

def run_one(filepath: str,
            chunk_size: int = 1024,
            timeout: float = 1.0,
            loss_rate: float = 0.0,
            window_size: int = 1,
            port: int = 9999,
            tag: str = '') -> dict:
    """Run one server+client pair and return client metrics."""
    from client import send_file

    log_dir = 'logs'
    safe_tag = tag.replace(' ', '_').replace('/', '-')
    srv_log = os.path.join(log_dir, f'server_{safe_tag}.csv')
    cli_log = os.path.join(log_dir, f'client_{safe_tag}.csv')

    print(f'\n{"="*60}')
    print(f'  Experiment: {tag}')
    print(f'  chunk={chunk_size}B  timeout={timeout}s  loss={loss_rate:.0%}  window={window_size}')
    print(f'{"="*60}')

    srv_t = _start_server(port, loss_rate, srv_log)

    result = send_file(
        filepath=filepath,
        host='127.0.0.1',
        port=port,
        timeout=timeout,
        chunk_size=chunk_size,
        loss_rate=loss_rate,
        window_size=window_size,
        log_path=cli_log,
    )

    srv_t.join(timeout=10)
    result['tag'] = tag
    return result


# ── Scenario 1: Packet size effect ───────────────────────────────────────────

def scenario_packet_size(base_file: str, port: int = 9991) -> list:
    """
    Vary chunk/packet size; observe throughput and completion time.
    Fixed: 512 KB file, timeout=1s, no loss, stop-and-wait.
    """
    chunk_sizes = [128, 256, 512, 1024, 2048, 4096]
    results = []
    for cs in chunk_sizes:
        r = run_one(base_file, chunk_size=cs, timeout=1.0, loss_rate=0.0,
                    port=port, tag=f'S1_chunk{cs}')
        r['x_val'] = cs
        results.append(r)
        time.sleep(0.5)
    return results


# ── Scenario 2: Timeout value effect ─────────────────────────────────────────

def scenario_timeout(base_file: str, port: int = 9992) -> list:
    """
    Vary timeout value; observe unnecessary retransmissions and total delay.
    Fixed: 256 KB file, chunk=1024B, loss=5%, stop-and-wait.
    """
    timeouts = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0]
    results = []
    for to in timeouts:
        r = run_one(base_file, chunk_size=1024, timeout=to, loss_rate=0.05,
                    port=port, tag=f'S2_to{to}')
        r['x_val'] = to
        results.append(r)
        time.sleep(0.5)
    return results


# ── Scenario 3: Packet loss rate effect ──────────────────────────────────────

def scenario_loss_rate(base_file: str, port: int = 9993) -> list:
    """
    Vary simulated loss rate; observe retransmissions and goodput degradation.
    Fixed: 256 KB file, chunk=1024B, timeout=1s, stop-and-wait.
    """
    loss_rates = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20]
    results = []
    for lr in loss_rates:
        r = run_one(base_file, chunk_size=1024, timeout=1.0, loss_rate=lr,
                    port=port, tag=f'S3_loss{int(lr*100)}pct')
        r['x_val'] = lr * 100   # store as %
        results.append(r)
        time.sleep(0.5)
    return results


# ── Scenario 4: File size effect ─────────────────────────────────────────────

def scenario_file_size(files: dict, port: int = 9994) -> list:
    """
    Vary file size; observe system efficiency at different scales.
    Fixed: chunk=1024B, timeout=1s, no loss, stop-and-wait.
    files: {label: path}
    """
    results = []
    for label, path in files.items():
        r = run_one(path, chunk_size=1024, timeout=1.0, loss_rate=0.0,
                    port=port, tag=f'S4_{label}')
        r['x_val'] = r['file_size'] / 1024   # KB
        results.append(r)
        time.sleep(0.5)
    return results


# ── BONUS: Sliding window vs Stop-and-Wait ────────────────────────────────────

def scenario_window_size(base_file: str, port: int = 9995) -> list:
    """
    Compare window sizes 1 (S&W) through 16.
    Fixed: 512 KB file, chunk=1024B, timeout=0.5s, no loss.
    """
    window_sizes = [1, 2, 4, 8, 16]
    results = []
    for ws in window_sizes:
        r = run_one(base_file, chunk_size=1024, timeout=0.5, loss_rate=0.0,
                    window_size=ws, port=port, tag=f'BONUS_win{ws}')
        r['x_val'] = ws
        results.append(r)
        time.sleep(0.5)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs('test_data', exist_ok=True)
    os.makedirs('results',   exist_ok=True)
    os.makedirs('logs',      exist_ok=True)

    # Create test files
    files = {
        '32KB':  'test_data/file_32k.bin',
        '128KB': 'test_data/file_128k.bin',
        '256KB': 'test_data/file_256k.bin',
        '512KB': 'test_data/file_512k.bin',
        '1MB':   'test_data/file_1m.bin',
    }
    sizes = {
        '32KB':  32 * 1024,
        '128KB': 128 * 1024,
        '256KB': 256 * 1024,
        '512KB': 512 * 1024,
        '1MB':   1024 * 1024,
    }
    for label, path in files.items():
        if not os.path.exists(path):
            _make_file(path, sizes[label])

    from analyzer import plot_experiment, plot_combined, save_summary_csv

    all_results = {}

    # ── Scenario 1 ────────────────────────────────────────────────────────────
    print('\n\n' + '█'*60)
    print('  SCENARIO 1: Packet Size Effect')
    print('█'*60)
    s1 = scenario_packet_size(files['512KB'], port=9991)
    plot_experiment(s1, 'Chunk Size (bytes)', [r['x_val'] for r in s1],
                    'Scenario 1 – Effect of Packet Size', 'results')
    all_results['S1 Packet Size'] = s1

    # ── Scenario 2 ────────────────────────────────────────────────────────────
    print('\n\n' + '█'*60)
    print('  SCENARIO 2: Timeout Value Effect')
    print('█'*60)
    s2 = scenario_timeout(files['256KB'], port=9992)
    plot_experiment(s2, 'Timeout (s)', [r['x_val'] for r in s2],
                    'Scenario 2 – Effect of Timeout Value', 'results')
    all_results['S2 Timeout'] = s2

    # ── Scenario 3 ────────────────────────────────────────────────────────────
    print('\n\n' + '█'*60)
    print('  SCENARIO 3: Packet Loss Rate Effect')
    print('█'*60)
    s3 = scenario_loss_rate(files['256KB'], port=9993)
    plot_experiment(s3, 'Loss Rate (%)', [r['x_val'] for r in s3],
                    'Scenario 3 – Effect of Packet Loss Rate', 'results')
    all_results['S3 Loss Rate'] = s3

    # ── Scenario 4 ────────────────────────────────────────────────────────────
    print('\n\n' + '█'*60)
    print('  SCENARIO 4: File Size Effect')
    print('█'*60)
    s4 = scenario_file_size(files, port=9994)
    plot_experiment(s4, 'File Size (KB)', [r['x_val'] for r in s4],
                    'Scenario 4 – Effect of File Size', 'results')
    all_results['S4 File Size'] = s4

    # ── BONUS 1: Sliding Window ───────────────────────────────────────────────
    print('\n\n' + '='*60)
    print('  BONUS 1: Sliding Window vs Stop-and-Wait')
    print('='*60)
    sb = scenario_window_size(files['512KB'], port=9995)
    plot_experiment(sb, 'Window Size', [r['x_val'] for r in sb],
                    'Bonus 1 – Sliding Window Effect', 'results')
    all_results['Bonus1 Window'] = sb

    # ── BONUS 2: TCP vs UDP comparison ────────────────────────────────────────
    print('\n\n' + '='*60)
    print('  BONUS 2: TCP vs UDP Comparison')
    print('='*60)
    try:
        from tcp_compare import run_comparison
        cmp = run_comparison(files['256KB'])
        all_results['Bonus2 TCP-vs-UDP'] = [cmp['tcp'], cmp['udp']]
    except Exception as e:
        print(f'[EXP] TCP comparison skipped: {e}')

    # ── BONUS 3: Compression / Encryption effect ──────────────────────────────
    print('\n\n' + '='*60)
    print('  BONUS 3: Compression & Encryption Effect on Throughput')
    print('='*60)
    crypto_results = []
    crypto_modes   = ['none', 'compress', 'encrypt', 'compress+encrypt']
    for mode in crypto_modes:
        tag = f'BONUS3_crypto_{mode}'
        from server import serve_once
        from client import send_file as _sf
        srv_log = f'logs/server_{tag}.csv'
        cli_log = f'logs/client_{tag}.csv'

        def _srv_b3(m=mode, tg=tag):
            serve_once('127.0.0.1', 19880, 'received', 0.0, srv_log, 20)

        t_b3 = threading.Thread(target=_srv_b3, daemon=True)
        t_b3.start(); time.sleep(0.3)

        r_b3 = _sf(files['128KB'], '127.0.0.1', 19880,
                   timeout=1.0, chunk_size=1024, loss_rate=0.0,
                   window_size=1, log_path=cli_log,
                   crypto_mode=mode, crypto_key='netprobe2025')
        t_b3.join(5)
        r_b3['x_val'] = mode
        r_b3['tag']   = tag
        crypto_results.append(r_b3)
        time.sleep(0.5)

    # bar chart for crypto comparison
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import os as _os

        labels_c = [r['x_val'] for r in crypto_results]
        gp_vals  = [r['goodput']/1024 for r in crypto_results]
        dur_vals = [r['duration'] for r in crypto_results]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
        fig.suptitle('Bonus 3 – Effect of Compression & Encryption', fontsize=12)
        ax1.bar(labels_c, gp_vals, color='#a6e3a1'); ax1.set_title('Goodput (KB/s)'); ax1.set_ylim(bottom=0)
        ax2.bar(labels_c, dur_vals, color='#fab387'); ax2.set_title('Duration (s)'); ax2.set_ylim(bottom=0)
        plt.tight_layout()
        plt.savefig('results/Bonus3_crypto_comparison.png', dpi=150); plt.close()
        print('[EXP] Crypto comparison plot saved.')
    except Exception as e:
        print(f'[EXP] Crypto plot skipped: {e}')

    all_results['Bonus3 Crypto'] = crypto_results

    # ── BONUS 4: PCAP capture demo ────────────────────────────────────────────
    print('\n\n' + '='*60)
    print('  BONUS 4: PCAP Capture (Wireshark-compatible)')
    print('='*60)
    try:
        from pcap_writer import serve_with_capture
        from client import send_file as _sfp

        def _pcap_srv():
            serve_with_capture('127.0.0.1', 19870, 'received',
                               'results/capture.pcap', 0.0,
                               'logs/pcap_srv.csv')

        t_pcap = threading.Thread(target=_pcap_srv, daemon=True)
        t_pcap.start(); time.sleep(0.3)
        _sfp('test_data/file_32k.bin', '127.0.0.1', 19870,
             timeout=1.0, chunk_size=1024, loss_rate=0.0,
             log_path='logs/pcap_cli.csv')
        t_pcap.join(10)
        print('[EXP] PCAP capture: results/capture.pcap  (open in Wireshark)')
    except Exception as e:
        print(f'[EXP] PCAP capture skipped: {e}')

    # ── Combined summary ──────────────────────────────────────────────────────
    plot_combined(all_results, 'results')

    all_flat = [r for results in all_results.values() for r in results]
    save_summary_csv(all_flat, 'results/summary.csv')

    print('\n\n' + '='*60)
    print('  All experiments complete.')
    print('  Results in: results/')
    print('  Logs in:    logs/')
    print('='*60)


if __name__ == '__main__':
    main()
