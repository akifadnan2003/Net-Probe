"""
NetProbe – Multi-Client UDP Server (Bonus)

Handles multiple simultaneous clients by tracking each (host, port) address
as an independent transfer session.  Each session gets its own buffer,
logger, and state machine — all managed in a single event loop thread.

Usage:
  python multi_client_server.py [--port 9999] [--loss 0.0]

Then send from multiple clients simultaneously:
  python client.py file_a.bin --port 9999
  python client.py file_b.bin --port 9999   # in another terminal
"""

import socket
import time
import hashlib
import os
import random
import argparse
from dataclasses import dataclass, field
from typing import Dict, Optional

from protocol import parse_data, parse_fin, build_ack, build_fin_ack
from logger import Logger


@dataclass
class Session:
    addr: tuple
    total: int
    start_time: float
    received: Dict[int, bytes] = field(default_factory=dict)
    acks_sent: int = 0
    duplicates: int = 0
    last_activity: float = field(default_factory=time.time)
    log: Optional[Logger] = None
    done: bool = False


def run_multi_server(host: str = '0.0.0.0',
                     port: int = 9999,
                     output_dir: str = 'received',
                     loss_rate: float = 0.0,
                     session_timeout: float = 30.0):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(1.0)      # short timeout so we can reap dead sessions

    sessions: Dict[tuple, Session] = {}
    print(f'[MULTI-SRV] Listening on {host}:{port}  loss={loss_rate:.0%}')

    while True:
        # ── reap timed-out sessions ───────────────────────────────────────────
        now = time.time()
        dead = [a for a, s in sessions.items()
                if not s.done and now - s.last_activity > session_timeout]
        for addr in dead:
            s = sessions[addr]
            print(f'[MULTI-SRV] Session {addr} timed out  '
                  f'({len(s.received)}/{s.total})')
            if s.log:
                s.log.close()
            del sessions[addr]

        # ── receive next datagram ─────────────────────────────────────────────
        try:
            raw, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue

        if random.random() < loss_rate:
            continue

        # ── FIN? ─────────────────────────────────────────────────────────────
        fin_md5 = parse_fin(raw)
        if fin_md5 is not None and addr in sessions:
            s = sessions[addr]
            s.last_activity = time.time()

            ok = False
            if len(s.received) == s.total:
                file_data  = b''.join(s.received[i] for i in range(s.total))
                actual_md5 = hashlib.md5(file_data).hexdigest()
                ok         = (actual_md5 == fin_md5)

                out = os.path.join(output_dir,
                                   f'mc_{addr[1]}_{int(time.time())}.bin')
                with open(out, 'wb') as f:
                    f.write(file_data)
                duration = time.time() - s.start_time
                print(f'[MULTI-SRV] {addr} done  ok={ok}  '
                      f'{len(file_data):,}B  {duration:.2f}s')
                if s.log:
                    s.log.log('TRANSFER_COMPLETE', seq=-1,
                              ok=ok, duration=f'{duration:.3f}')
            else:
                print(f'[MULTI-SRV] {addr} incomplete: '
                      f'{len(s.received)}/{s.total}')

            sock.sendto(build_fin_ack(ok), addr)
            s.done = True
            if s.log:
                s.log.close()
            del sessions[addr]
            continue

        # ── DATA ─────────────────────────────────────────────────────────────
        result = parse_data(raw)
        if result is None:
            continue

        seq, total, payload = result

        if addr not in sessions:
            log_path = os.path.join('logs', f'mc_srv_{addr[1]}.csv')
            s = Session(addr=addr, total=total,
                        start_time=time.time(),
                        log=Logger(log_path))
            sessions[addr] = s
            print(f'[MULTI-SRV] New session {addr}  total={total}  '
                  f'(active sessions: {len(sessions)})')
            s.log.log('TRANSFER_START', seq=seq, total=total, addr=str(addr))

        s = sessions[addr]
        s.last_activity = time.time()

        # send ACK regardless (handles duplicates transparently)
        sock.sendto(build_ack(seq), addr)
        s.acks_sent += 1

        if seq in s.received:
            s.duplicates += 1
            if s.log:
                s.log.log('DUPLICATE', seq=seq)
        else:
            s.received[seq] = payload
            if s.log:
                s.log.log('PACKET_RECEIVED', seq=seq,
                           progress=f'{len(s.received)}/{s.total}')


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe Multi-Client Server')
    p.add_argument('--host',    default='0.0.0.0')
    p.add_argument('--port',    default=9999,  type=int)
    p.add_argument('--out',     default='received')
    p.add_argument('--loss',    default=0.0,   type=float)
    p.add_argument('--timeout', default=30.0,  type=float,
                   help='Session idle timeout (s)')
    a = p.parse_args()
    run_multi_server(a.host, a.port, a.out, a.loss, a.timeout)
