"""
NetProbe – Real-time Transfer Visualization Panel

Reads the client log CSV live (tail -f style) and draws an animated
matplotlib dashboard: packet timeline, RTT, cumulative goodput.

Usage (run while a transfer is happening):
  python realtime_viz.py --log logs/client_log.csv [--interval 500]

Or import and call start_dashboard(log_path) from experiments.py.
"""

import os
import csv
import time
import ast
import argparse
import threading
import collections

try:
    import matplotlib
    matplotlib.use('TkAgg')          # interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    HAS_MPL = True
except Exception:
    HAS_MPL = False


# ── Log reader (non-blocking tail) ───────────────────────────────────────────

class LiveLogReader:
    def __init__(self, path: str):
        self.path   = path
        self._lines = []
        self._pos   = 0
        self._lock  = threading.Lock()
        self._t     = threading.Thread(target=self._watch, daemon=True)
        self._t.start()

    def _watch(self):
        while not os.path.exists(self.path):
            time.sleep(0.1)
        with open(self.path, 'r', encoding='utf-8') as f:
            f.readline()            # skip header
            while True:
                line = f.readline()
                if line:
                    with self._lock:
                        self._lines.append(line.strip())
                else:
                    time.sleep(0.05)

    def drain(self):
        with self._lock:
            batch = self._lines[self._pos:]
            self._pos = len(self._lines)
        return batch


# ── Dashboard ─────────────────────────────────────────────────────────────────

def start_dashboard(log_path: str, interval_ms: int = 300):
    """
    Open a live matplotlib window with 4 subplots.
    Blocks until the window is closed.
    """
    if not HAS_MPL:
        print('[VIZ] matplotlib not available – skipping dashboard.')
        return

    reader = LiveLogReader(log_path)

    # rolling data
    MAX_POINTS = 500
    rtt_times  = collections.deque(maxlen=MAX_POINTS)
    rtt_vals   = collections.deque(maxlen=MAX_POINTS)
    events_x   = collections.deque(maxlen=MAX_POINTS)   # timestamp
    events_y   = collections.deque(maxlen=MAX_POINTS)   # seq
    events_c   = collections.deque(maxlen=MAX_POINTS)   # color
    gput_x     = collections.deque(maxlen=MAX_POINTS)
    gput_y     = collections.deque(maxlen=MAX_POINTS)
    retrans_x  = collections.deque(maxlen=MAX_POINTS)
    retrans_y  = collections.deque(maxlen=MAX_POINTS)

    cumulative_bytes = [0]
    retrans_count    = [0]
    t_start          = [None]
    total_pkts       = [None]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle('NetProbe – Live Transfer Dashboard', fontsize=13, fontweight='bold')
    fig.patch.set_facecolor('#1e1e2e')
    for ax in axes.flat:
        ax.set_facecolor('#2a2a3e')
        ax.tick_params(colors='#cdd6f4')
        ax.spines['bottom'].set_color('#585b70')
        ax.spines['left'].set_color('#585b70')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.xaxis.label.set_color('#cdd6f4')
        ax.yaxis.label.set_color('#cdd6f4')
        ax.title.set_color('#cba6f7')

    # Axis labels
    axes[0,0].set_title('Packet Timeline  (green=SENT  red=TIMEOUT  orange=RETRANS)')
    axes[0,0].set_xlabel('Time (s)')
    axes[0,0].set_ylabel('Sequence Number')

    axes[0,1].set_title('RTT per Packet')
    axes[0,1].set_xlabel('Time (s)')
    axes[0,1].set_ylabel('RTT (ms)')

    axes[1,0].set_title('Cumulative Goodput')
    axes[1,0].set_xlabel('Time (s)')
    axes[1,0].set_ylabel('KB transferred')

    axes[1,1].set_title('Retransmission Count')
    axes[1,1].set_xlabel('Time (s)')
    axes[1,1].set_ylabel('Cumulative Retrans')

    def _color(event):
        if event == 'PACKET_SENT':     return '#a6e3a1'
        if event == 'TIMEOUT':         return '#f38ba8'
        if 'RETRANS' in event:         return '#fab387'
        if event == 'ACK_RECEIVED':    return '#89dceb'
        if event == 'PACKET_DROPPED':  return '#cba6f7'
        return '#585b70'

    def _update(_frame):
        for raw in reader.drain():
            parts = raw.split(',', 3)
            if len(parts) < 4:
                continue
            ts_str, event, seq_str, details_str = parts
            try:
                ts  = float(ts_str)
                seq = int(seq_str)
            except ValueError:
                continue

            if t_start[0] is None and event in ('PACKET_SENT', 'TRANSFER_START'):
                t_start[0] = ts

            rel = ts - t_start[0] if t_start[0] else 0

            # parse details
            det = {}
            try:
                det = ast.literal_eval(details_str)
            except Exception:
                pass

            if event == 'TRANSFER_START':
                total_pkts[0] = det.get('total', None)

            if event == 'PACKET_SENT':
                attempt = det.get('attempt', 0)
                c = '#fab387' if attempt > 0 else '#a6e3a1'
                events_x.append(rel); events_y.append(seq); events_c.append(c)
                cumulative_bytes[0] += det.get('chunk', 1024)
                gput_x.append(rel)
                gput_y.append(cumulative_bytes[0] / 1024)
                if attempt > 0:
                    retrans_count[0] += 1
                    retrans_x.append(rel)
                    retrans_y.append(retrans_count[0])

            if event == 'TIMEOUT':
                events_x.append(rel); events_y.append(seq); events_c.append('#f38ba8')

            if event == 'ACK_RECEIVED':
                rtt_ms = float(det.get('rtt', 0)) * 1000
                rtt_times.append(rel)
                rtt_vals.append(rtt_ms)

        # redraw
        for ax in axes.flat:
            ax.cla()

        # timeline
        if events_x:
            axes[0,0].scatter(list(events_x), list(events_y),
                              c=list(events_c), s=12, alpha=0.8, linewidths=0)
        axes[0,0].set_title('Packet Timeline  (green=SENT  orange=RETRANS  red=TIMEOUT)')
        axes[0,0].set_xlabel('Time (s)'); axes[0,0].set_ylabel('Sequence Number')

        # RTT
        if rtt_times:
            axes[0,1].plot(list(rtt_times), list(rtt_vals),
                           color='#89dceb', linewidth=1, alpha=0.9)
            axes[0,1].fill_between(list(rtt_times), list(rtt_vals),
                                   alpha=0.2, color='#89dceb')
        axes[0,1].set_title('RTT per Packet')
        axes[0,1].set_xlabel('Time (s)'); axes[0,1].set_ylabel('RTT (ms)')

        # Goodput
        if gput_x:
            axes[1,0].plot(list(gput_x), list(gput_y),
                           color='#a6e3a1', linewidth=2)
            axes[1,0].fill_between(list(gput_x), list(gput_y),
                                   alpha=0.25, color='#a6e3a1')
        axes[1,0].set_title('Cumulative Goodput')
        axes[1,0].set_xlabel('Time (s)'); axes[1,0].set_ylabel('KB transferred')

        # Retrans
        if retrans_x:
            axes[1,1].step(list(retrans_x), list(retrans_y),
                           color='#f38ba8', linewidth=2, where='post')
        axes[1,1].set_title(f'Retransmissions (total: {retrans_count[0]})')
        axes[1,1].set_xlabel('Time (s)'); axes[1,1].set_ylabel('Cumulative Retrans')

        for ax in axes.flat:
            ax.set_facecolor('#2a2a3e')
            ax.tick_params(colors='#cdd6f4')

    ani = animation.FuncAnimation(fig, _update, interval=interval_ms,
                                  cache_frame_data=False)
    plt.tight_layout()
    try:
        plt.show()
    except Exception:
        pass
    return ani


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe Real-time Visualization')
    p.add_argument('--log',      default='logs/client_log.csv')
    p.add_argument('--interval', default=300, type=int, help='Refresh ms')
    a = p.parse_args()
    start_dashboard(a.log, a.interval)
