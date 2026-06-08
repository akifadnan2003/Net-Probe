"""
NetProbe – TCP vs UDP Comparative Experiment (Bonus)

Sends the same file over both TCP and our UDP protocol, then
plots a side-by-side comparison of throughput, goodput, and completion time.

Usage:
  # Terminal 1 – start both servers
  python tcp_compare.py --server

  # Terminal 2 – run comparison
  python tcp_compare.py --file test_data/file_256k.bin

Or run everything in one process (auto-threaded):
  python tcp_compare.py --auto --file test_data/file_256k.bin
"""

import socket
import time
import hashlib
import os
import threading
import argparse

TCP_PORT = 19001
UDP_PORT = 19002
CHUNK    = 1024

# ── TCP server (minimal, one transfer) ───────────────────────────────────────

def tcp_server(host: str = '127.0.0.1', port: int = TCP_PORT,
               output_dir: str = 'received') -> dict:
    os.makedirs(output_dir, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    srv.settimeout(30)
    print(f'[TCP-SRV] Listening on {host}:{port}')

    conn, addr = srv.accept()
    conn.settimeout(30)
    print(f'[TCP-SRV] Connection from {addr}')

    # First 8 bytes: expected file size (so we know when we're done)
    size_hdr = b''
    while len(size_hdr) < 8:
        size_hdr += conn.recv(8 - len(size_hdr))
    expected = int.from_bytes(size_hdr, 'big')

    t_start = time.time()
    data    = b''
    while len(data) < expected:
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
    t_end = time.time()

    # Send ACK so client can measure RTT properly
    conn.sendall(b'OK')
    duration = t_end - t_start

    actual_md5 = hashlib.md5(data).hexdigest()
    out = os.path.join(output_dir, f'tcp_received_{int(time.time())}.bin')
    with open(out, 'wb') as f:
        f.write(data)

    conn.close()
    srv.close()
    size_kb = len(data)/1024
    gput    = len(data)/duration if duration > 0 else 0
    print(f'[TCP-SRV] Done  {size_kb:.1f} KB in {duration:.4f}s  '
          f'goodput={gput/1024:.1f} KB/s  MD5={actual_md5[:8]}...')
    return dict(duration=duration, file_size=len(data),
                goodput=gput, throughput=gput,
                retransmissions=0, file_ok=True)


# ── TCP client ────────────────────────────────────────────────────────────────

def tcp_client(filepath: str, host: str = '127.0.0.1',
               port: int = TCP_PORT) -> dict:
    with open(filepath, 'rb') as f:
        data = f.read()

    print(f'[TCP-CLI] Sending {len(data):,} bytes over TCP...')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))

    # Send size header first so server knows when file ends
    sock.sendall(len(data).to_bytes(8, 'big'))

    t_start = time.time()
    sock.sendall(data)

    # Wait for server ACK to get accurate end-to-end duration
    sock.settimeout(10)
    try:
        sock.recv(2)   # 'OK'
    except socket.timeout:
        pass
    t_end    = time.time()
    sock.close()

    duration = t_end - t_start
    file_md5 = hashlib.md5(data).hexdigest()
    goodput  = len(data) / duration if duration > 0 else 0

    print(f'[TCP-CLI] Done in {duration:.4f}s  Goodput={goodput/1024:.1f} KB/s')
    return dict(duration=duration, file_size=len(data),
                goodput=goodput, throughput=goodput,
                retransmissions=0, file_ok=True, md5=file_md5)


# ── UDP transfer (reuse client.py) ───────────────────────────────────────────

def udp_transfer(filepath: str, host: str = '127.0.0.1',
                 port: int = UDP_PORT) -> dict:
    from server import serve_once
    from client import send_file

    results = [None]
    def _srv():
        results[0] = serve_once(host, port, 'received', 0.0,
                                'logs/tcp_cmp_srv.csv', 30)
    t = threading.Thread(target=_srv, daemon=True)
    t.start()
    time.sleep(0.3)

    r = send_file(filepath, host, port, timeout=1.0, chunk_size=CHUNK,
                  loss_rate=0.0, window_size=1,
                  log_path='logs/tcp_cmp_cli.csv')
    t.join(timeout=10)
    return r


# ── Plot comparison ───────────────────────────────────────────────────────────

def plot_comparison(tcp_r: dict, udp_r: dict, output_dir: str = 'results'):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('[CMP] matplotlib missing – skipping plot.')
        return

    os.makedirs(output_dir, exist_ok=True)
    labels   = ['TCP', 'UDP (NetProbe)']
    colors   = ['#89b4fa', '#a6e3a1']

    metrics = {
        'Goodput (KB/s)':    [tcp_r['goodput']/1024,   udp_r['goodput']/1024],
        'Throughput (KB/s)': [tcp_r['throughput']/1024, udp_r['throughput']/1024],
        'Duration (s)':      [tcp_r['duration'],         udp_r['duration']],
    }

    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    fig.suptitle('TCP vs UDP (NetProbe) – Same File, Same Conditions',
                 fontsize=13, fontweight='bold')

    for ax, (title, vals) in zip(axes, metrics.items()):
        bars = ax.bar(labels, vals, color=colors, width=0.45, edgecolor='#313244')
        ax.set_title(title, fontsize=11)
        ax.set_ylim(bottom=0)
        ax.grid(axis='y', linestyle='--', alpha=0.4)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(vals)*0.01,
                    f'{v:.1f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    plt.tight_layout()
    out = os.path.join(output_dir, 'tcp_vs_udp_comparison.png')
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[CMP] Plot saved: {out}')
    return out


# ── Auto mode: run both in one call ──────────────────────────────────────────

def run_comparison(filepath: str, host: str = '127.0.0.1') -> dict:
    print('\n' + '='*55)
    print('  TCP vs UDP Comparison')
    print('='*55)

    # TCP
    tcp_stats = [None]
    def _tcp_srv():
        tcp_stats[0] = tcp_server(host, TCP_PORT)
    t_srv = threading.Thread(target=_tcp_srv, daemon=True)
    t_srv.start()
    time.sleep(0.3)
    tcp_cli = tcp_client(filepath, host, TCP_PORT)
    t_srv.join(timeout=10)

    # UDP (our protocol)
    print()
    udp_cli = udp_transfer(filepath, host, UDP_PORT)

    # Report
    print('\n' + '-'*55)
    print(f'{"Metric":<25} {"TCP":>12} {"UDP (NetProbe)":>15}')
    print('-'*55)
    for key, label in [('goodput','Goodput (KB/s)'),('duration','Duration (s)')]:
        t_v = tcp_cli.get(key, 0)
        u_v = udp_cli.get(key, 0)
        if key == 'goodput':
            print(f'{label:<25} {t_v/1024:>12.1f} {u_v/1024:>15.1f}')
        else:
            print(f'{label:<25} {t_v:>12.3f} {u_v:>15.3f}')
    print('-'*55)
    print('Note: UDP overhead includes per-packet ACK round-trips (Stop-and-Wait).')
    print('      Use --window 8 on NetProbe for closer-to-TCP throughput.')

    plot_comparison(tcp_cli, udp_cli)
    return dict(tcp=tcp_cli, udp=udp_cli)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe TCP vs UDP Comparison')
    p.add_argument('--file',   default='test_data/file_256k.bin')
    p.add_argument('--host',   default='127.0.0.1')
    p.add_argument('--server', action='store_true', help='Run server side only')
    p.add_argument('--auto',   action='store_true', help='Auto run both sides')
    a = p.parse_args()

    if a.server:
        print('Starting TCP server…')
        tcp_server(a.host, TCP_PORT)
    else:
        run_comparison(a.file, a.host)
