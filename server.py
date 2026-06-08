"""
NetProbe – UDP Server

Usage:
  python server.py [--host 0.0.0.0] [--port 9999] [--out received]
                   [--loss 0.0] [--log logs/server_log.csv]

The server handles one transfer at a time (sequential).  Use serve_once()
from experiments.py to handle a single transfer and return stats.
"""

import socket
import time
import hashlib
import os
import random
import argparse

from protocol import (
    parse_data, parse_fin, build_ack, build_fin_ack,
    PACKET_TYPE_FIN,
)
from logger import Logger


def serve_once(host: str = '0.0.0.0',
               port: int = 9999,
               output_dir: str = 'received',
               loss_rate: float = 0.0,
               log_path: str = 'logs/server_log.csv',
               idle_timeout: float = 30.0) -> dict:
    """
    Block until one complete transfer is received, then return stats dict.
    loss_rate: probability [0,1) of silently dropping an incoming packet
                (simulates network packet loss for experiments).
    """
    os.makedirs(output_dir, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(None)   # block until first packet

    print(f'[SERVER] Listening on {host}:{port}  (loss_rate={loss_rate:.0%})')

    with Logger(log_path) as logger:
        received   = {}          # seq → payload
        total      = None
        client_addr = None
        start_time = None
        stats = dict(acks_sent=0, duplicates=0, corrupt=0,
                     packets_received=0, fin_received=False)

        while True:
            try:
                raw, addr = sock.recvfrom(65535)
            except socket.timeout:
                print('[SERVER] Idle timeout – no client.')
                break

            # ── simulate packet loss ──────────────────────────────────────────
            if random.random() < loss_rate:
                logger.log('PACKET_DROPPED_SIM', seq=-1, addr=str(addr))
                continue

            # ── FIN? ─────────────────────────────────────────────────────────
            fin_md5 = parse_fin(raw)
            if fin_md5 is not None and addr == client_addr:
                stats['fin_received'] = True
                end_time = time.time()
                duration = end_time - start_time if start_time else 0

                # Reassemble
                ok = False
                file_data = b''
                if total is not None and len(received) == total:
                    file_data = b''.join(received[i] for i in range(total))
                    actual_md5 = hashlib.md5(file_data).hexdigest()
                    ok = (actual_md5 == fin_md5)

                    out_path = os.path.join(
                        output_dir, f'file_{int(time.time())}.bin')
                    with open(out_path, 'wb') as fout:
                        fout.write(file_data)
                    print(f'[SERVER] Saved: {out_path}  MD5_ok={ok}')
                else:
                    print(f'[SERVER] Incomplete: {len(received)}/{total}')

                sock.sendto(build_fin_ack(ok), addr)
                logger.log('FIN_ACK_SENT', seq=-1, ok=ok, duration=f'{duration:.4f}',
                           received=len(received), total=total)

                stats.update(duration=duration, file_size=len(file_data),
                             file_ok=ok, packets_expected=total or 0,
                             packets_received=len(received))
                break

            # ── DATA ─────────────────────────────────────────────────────────
            result = parse_data(raw)
            if result is None:
                stats['corrupt'] += 1
                logger.log('CORRUPT_PACKET', seq=-1, addr=str(addr))
                continue

            seq, pkt_total, payload = result
            recv_time = time.time()

            if client_addr is None:
                client_addr = addr
                total      = pkt_total
                start_time = recv_time
                sock.settimeout(idle_timeout)
                print(f'[SERVER] Transfer from {addr}  total={total} packets')
                logger.log('TRANSFER_START', seq=seq, total=total, addr=str(addr))

            if addr != client_addr:
                continue   # ignore other senders

            # Send ACK (always, even for duplicates)
            sock.sendto(build_ack(seq), addr)
            stats['acks_sent'] += 1
            logger.log('ACK_SENT', seq=seq, ts=f'{recv_time:.6f}')

            if seq in received:
                stats['duplicates'] += 1
                logger.log('DUPLICATE', seq=seq)
                continue

            received[seq] = payload
            stats['packets_received'] += 1
            logger.log('PACKET_RECEIVED', seq=seq,
                       progress=f'{len(received)}/{total}')

    sock.close()
    return stats


def run_server(host: str = '0.0.0.0',
               port: int = 9999,
               output_dir: str = 'received',
               loss_rate: float = 0.0,
               log_path: str = 'logs/server_log.csv'):
    """Continuous loop – handles transfers one after another."""
    transfer_count = 0
    while True:
        transfer_count += 1
        print(f'\n[SERVER] === Transfer #{transfer_count} ===')
        stats = serve_once(host, port, output_dir, loss_rate, log_path)
        print(f'[SERVER] Stats: {stats}')


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description='NetProbe UDP Server')
    p.add_argument('--host',   default='0.0.0.0',             help='Bind address')
    p.add_argument('--port',   default=9999,    type=int,      help='UDP port')
    p.add_argument('--out',    default='received',             help='Output directory')
    p.add_argument('--loss',   default=0.0,     type=float,    help='Simulated packet loss rate [0,1)')
    p.add_argument('--log',    default='logs/server_log.csv',  help='Log file path')
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    run_server(args.host, args.port, args.out, args.loss, args.log)
