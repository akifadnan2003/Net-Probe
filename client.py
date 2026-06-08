"""
NetProbe – UDP Client

Usage:
  python client.py <file> [--host 127.0.0.1] [--port 9999]
                          [--timeout 1.0] [--chunk 1024]
                          [--loss 0.0] [--window 1]
                          [--mode none|compress|encrypt|compress+encrypt]
                          [--key <passphrase>]
                          [--log logs/client_log.csv]

window=1  → Stop-and-Wait (default, meets base requirement)
window>1  → Sliding Window / Go-Back-N (bonus feature)
--mode    → optional compression / encryption before transmission (bonus)
"""

import socket
import time
import hashlib
import os
import random
import threading
import argparse

from protocol import (
    build_data, parse_ack, build_fin, parse_fin_ack,
    DEFAULT_CHUNK_SIZE, DEFAULT_TIMEOUT, MAX_RETRIES,
)
from logger import Logger


# ── Stop-and-Wait sender ──────────────────────────────────────────────────────

def _send_stop_and_wait(sock, chunks, total, host, port,
                        timeout, loss_rate, logger, stats):
    for seq, chunk in enumerate(chunks):
        packet = build_data(seq, total, chunk)
        success = False

        for attempt in range(MAX_RETRIES + 1):
            # simulate outgoing loss
            if random.random() < loss_rate:
                logger.log('PACKET_DROPPED_SIM', seq=seq, attempt=attempt)
                stats['timeouts'] += 1
                if attempt > 0:
                    stats['retransmissions'] += 1
                time.sleep(timeout)
                continue

            t_send = time.time()
            sock.sendto(packet, (host, port))
            stats['sent'] += 1
            logger.log('PACKET_SENT', seq=seq, attempt=attempt,
                       ts=f'{t_send:.6f}')
            if attempt > 0:
                stats['retransmissions'] += 1

            try:
                sock.settimeout(timeout)
                raw, _ = sock.recvfrom(512)
                t_ack = time.time()
                ack_num = parse_ack(raw)
                if ack_num == seq:
                    rtt = t_ack - t_send
                    stats['acked'] += 1
                    stats['rtt_samples'].append(rtt)
                    logger.log('ACK_RECEIVED', seq=seq, rtt=f'{rtt:.6f}')
                    success = True
                    break
            except socket.timeout:
                stats['timeouts'] += 1
                logger.log('TIMEOUT', seq=seq, attempt=attempt)
                print(f'[CLIENT]  Timeout seq={seq} attempt={attempt + 1}/{MAX_RETRIES}')

        if not success:
            stats['failed_packets'] += 1
            logger.log('PACKET_FAILED', seq=seq)
            print(f'[CLIENT]  FAILED seq={seq} after {MAX_RETRIES} retries')


# ── Sliding-Window sender (Go-Back-N style) ───────────────────────────────────

def _send_sliding_window(sock, chunks, total, host, port,
                         timeout, loss_rate, window_size, logger, stats):
    """
    Sender keeps up to `window_size` unACKed packets in flight.
    A background thread reads ACKs; the main thread manages sends and timers.
    """
    lock      = threading.Lock()
    acked     = set()
    base      = [0]          # oldest unACKed seq
    next_seq  = [0]          # next packet to first-send
    send_time = {}           # seq → last send timestamp
    retries   = {}           # seq → attempt count
    done      = threading.Event()

    def ack_receiver():
        while not done.is_set():
            try:
                sock.settimeout(0.05)
                raw, _ = sock.recvfrom(512)
                ack_num = parse_ack(raw)
                if ack_num is None:
                    continue
                t_ack = time.time()
                with lock:
                    if ack_num not in acked:
                        acked.add(ack_num)
                        stats['acked'] += 1
                        rtt = t_ack - send_time.get(ack_num, t_ack)
                        stats['rtt_samples'].append(rtt)
                        logger.log('ACK_RECEIVED', seq=ack_num, rtt=f'{rtt:.6f}')
                    # advance base
                    while base[0] in acked and base[0] < total:
                        base[0] += 1
            except socket.timeout:
                pass

    recv_t = threading.Thread(target=ack_receiver, daemon=True)
    recv_t.start()

    def _do_send(seq, attempt):
        if random.random() < loss_rate:
            logger.log('PACKET_DROPPED_SIM', seq=seq, attempt=attempt)
            return False
        pkt = build_data(seq, total, chunks[seq])
        sock.sendto(pkt, (host, port))
        send_time[seq] = time.time()
        stats['sent'] += 1
        logger.log('PACKET_SENT', seq=seq, attempt=attempt,
                   ts=f'{send_time[seq]:.6f}')
        return True

    while True:
        with lock:
            cur_base = base[0]

        if cur_base >= total:
            break

        with lock:
            # Send new packets that fit in the window
            while next_seq[0] < total and next_seq[0] < cur_base + window_size:
                s = next_seq[0]
                retries[s] = 0
                _do_send(s, 0)
                next_seq[0] += 1

            # Check timeouts for in-flight packets
            now = time.time()
            for s in range(cur_base, min(next_seq[0], total)):
                if s in acked:
                    continue
                if s not in send_time:
                    continue
                if now - send_time[s] < timeout:
                    continue
                # timeout
                stats['timeouts'] += 1
                logger.log('TIMEOUT', seq=s, attempt=retries.get(s, 0))
                if retries.get(s, 0) >= MAX_RETRIES:
                    stats['failed_packets'] += 1
                    acked.add(s)          # give up on this packet
                    logger.log('PACKET_FAILED', seq=s)
                    while base[0] in acked and base[0] < total:
                        base[0] += 1
                else:
                    retries[s] = retries.get(s, 0) + 1
                    stats['retransmissions'] += 1
                    _do_send(s, retries[s])

        time.sleep(0.001)   # avoid busy-loop

    done.set()
    recv_t.join(timeout=1)


# ── Public API ────────────────────────────────────────────────────────────────

def send_file(filepath: str,
              host: str = '127.0.0.1',
              port: int = 9999,
              timeout: float = DEFAULT_TIMEOUT,
              chunk_size: int = DEFAULT_CHUNK_SIZE,
              loss_rate: float = 0.0,
              window_size: int = 1,
              log_path: str = 'logs/client_log.csv',
              crypto_mode: str = 'none',
              crypto_key: str = '') -> dict:
    """
    Send `filepath` to the server and return performance metrics.
    window_size=1 uses Stop-and-Wait; window_size>1 uses Sliding Window.
    crypto_mode: 'none' | 'compress' | 'encrypt' | 'compress+encrypt'
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    with open(filepath, 'rb') as f:
        raw_data = f.read()

    original_md5  = hashlib.md5(raw_data).hexdigest()
    original_size = len(raw_data)

    # Optional compression / encryption (bonus feature)
    if crypto_mode and crypto_mode != 'none':
        from crypto_compress import prepare
        data = prepare(raw_data, crypto_mode, crypto_key)
        print(f'[CLIENT] Crypto mode: {crypto_mode}  '
              f'{original_size:,}B -> {len(data):,}B '
              f'(ratio {original_size/max(len(data),1):.2f}x)')
    else:
        data = raw_data

    file_md5 = hashlib.md5(data).hexdigest()   # hash of what we actually send
    chunks   = [data[i: i + chunk_size] for i in range(0, max(len(data), 1), chunk_size)]
    total    = len(chunks)

    print(f'\n[CLIENT] File: {filepath}  ({len(data):,} bytes, {total} packets, '
          f'chunk={chunk_size}B, timeout={timeout}s, window={window_size}, '
          f'loss_sim={loss_rate:.0%})')
    print(f'[CLIENT] MD5: {file_md5}')

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    stats = dict(sent=0, acked=0, retransmissions=0, timeouts=0,
                 failed_packets=0, rtt_samples=[])

    with Logger(log_path) as logger:
        logger.log('TRANSFER_START', seq=0, file=filepath,
                   total=total, chunk=chunk_size, window=window_size,
                   loss=loss_rate)

        t_start = time.time()

        if window_size <= 1:
            _send_stop_and_wait(sock, chunks, total, host, port,
                                timeout, loss_rate, logger, stats)
        else:
            _send_sliding_window(sock, chunks, total, host, port,
                                 timeout, loss_rate, window_size, logger, stats)

        # ── FIN handshake ─────────────────────────────────────────────────────
        fin_pkt   = build_fin(file_md5)
        file_ok   = False
        sock.settimeout(timeout)
        for _ in range(5):
            sock.sendto(fin_pkt, (host, port))
            try:
                raw, _ = sock.recvfrom(64)
                status = parse_fin_ack(raw)
                if status is not None:
                    file_ok = status
                    break
            except (socket.timeout, ConnectionResetError):
                pass

        t_end    = time.time()
        duration = t_end - t_start

        # ── Metrics ───────────────────────────────────────────────────────────
        file_size    = len(data)
        total_tx_bytes = stats['sent'] * chunk_size    # approximate (last chunk may differ)
        throughput   = total_tx_bytes / duration if duration > 0 else 0
        goodput      = file_size / duration if duration > 0 else 0
        retrans_rate = stats['retransmissions'] / max(stats['sent'], 1)
        rtt_samples  = stats['rtt_samples']
        avg_rtt      = sum(rtt_samples) / len(rtt_samples) if rtt_samples else 0

        logger.log('TRANSFER_COMPLETE', seq=-1,
                   duration=f'{duration:.4f}',
                   throughput=f'{throughput:.2f}',
                   goodput=f'{goodput:.2f}',
                   retrans_rate=f'{retrans_rate:.4f}',
                   avg_rtt=f'{avg_rtt:.6f}',
                   failed=stats['failed_packets'],
                   file_ok=file_ok)

    sock.close()

    result = dict(
        file_size=file_size, total_packets=total,
        duration=duration,
        throughput=throughput, goodput=goodput,
        retransmissions=stats['retransmissions'],
        retrans_rate=retrans_rate,
        timeouts=stats['timeouts'],
        failed_packets=stats['failed_packets'],
        avg_rtt=avg_rtt,
        file_ok=file_ok,
        chunk_size=chunk_size, timeout=timeout,
        loss_rate=loss_rate, window_size=window_size,
    )

    print(f'\n[CLIENT] == Results =====================================')
    print(f'  Duration       : {duration:.3f} s')
    print(f'  Throughput     : {throughput/1024:.2f} KB/s')
    print(f'  Goodput        : {goodput/1024:.2f} KB/s')
    print(f'  Retrans rate   : {retrans_rate:.2%}')
    print(f'  Avg RTT        : {avg_rtt*1000:.2f} ms')
    print(f'  Timeouts       : {stats["timeouts"]}')
    print(f'  Failed packets : {stats["failed_packets"]}')
    print(f'  File integrity : {"OK" if file_ok else "FAILED"}')
    print(f'=========================================================')

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description='NetProbe UDP Client')
    p.add_argument('file',                                   help='File to send')
    p.add_argument('--host',    default='127.0.0.1',         help='Server host')
    p.add_argument('--port',    default=9999,   type=int,    help='Server port')
    p.add_argument('--timeout', default=1.0,    type=float,  help='ACK timeout (s)')
    p.add_argument('--chunk',   default=1024,   type=int,    help='Payload size (bytes)')
    p.add_argument('--loss',    default=0.0,    type=float,  help='Simulated loss [0,1)')
    p.add_argument('--window',  default=1,      type=int,    help='Sliding window size (1=S&W)')
    p.add_argument('--log',     default='logs/client_log.csv', help='Log file path')
    p.add_argument('--mode',    default='none',
                   choices=['none', 'compress', 'encrypt', 'compress+encrypt'],
                   help='Crypto/compression mode (bonus)')
    p.add_argument('--key',     default='',    help='Passphrase for encryption')
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    send_file(args.file, args.host, args.port,
              args.timeout, args.chunk, args.loss, args.window, args.log,
              args.mode, args.key)
