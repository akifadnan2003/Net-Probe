"""
NetProbe – PCAP Writer (Bonus – Wireshark/pcap support)

Writes captured UDP packets to a .pcap file that Wireshark can open.
No external libraries needed – writes the standard libpcap format manually.

Usage:
  from pcap_writer import PcapWriter
  writer = PcapWriter('capture.pcap')
  writer.write_packet(raw_bytes, src_ip, dst_ip, src_port, dst_port)
  writer.close()

Then open capture.pcap in Wireshark and filter: udp.port == 9999
"""

import struct
import time
import socket as _socket


# libpcap global header
_PCAP_MAGIC    = 0xa1b2c3d4
_PCAP_VERSION_MAJOR = 2
_PCAP_VERSION_MINOR = 4
_LINKTYPE_ETHERNET  = 1
_LINKTYPE_RAW_IP    = 101   # raw IPv4 – simplest, no Ethernet header needed

_GLOBAL_HDR_FMT = '<IHHiIII'   # little-endian
_PACKET_HDR_FMT = '<IIII'


class PcapWriter:
    """Writes raw UDP datagrams into a Wireshark-compatible .pcap file."""

    def __init__(self, path: str):
        self._f = open(path, 'wb')
        # global header
        self._f.write(struct.pack(
            _GLOBAL_HDR_FMT,
            _PCAP_MAGIC,
            _PCAP_VERSION_MAJOR,
            _PCAP_VERSION_MINOR,
            0,           # thiszone
            0,           # sigfigs
            65535,       # snaplen
            _LINKTYPE_RAW_IP,
        ))
        self._f.flush()
        print(f'[PCAP] Writing to {path}')

    def write_packet(self,
                     payload: bytes,
                     src_ip:   str   = '127.0.0.1',
                     dst_ip:   str   = '127.0.0.1',
                     src_port: int   = 0,
                     dst_port: int   = 9999,
                     ts:       float = None):
        """
        Wrap `payload` in a minimal IPv4 + UDP header and write a pcap record.
        """
        ts = ts or time.time()
        ts_sec  = int(ts)
        ts_usec = int((ts - ts_sec) * 1_000_000)

        # UDP header (8 bytes)
        udp_len = 8 + len(payload)
        udp_hdr = struct.pack('!HHHH',
                              src_port, dst_port, udp_len, 0)  # checksum=0

        # IPv4 header (20 bytes, minimal)
        ip_len  = 20 + udp_len
        src_b   = _socket.inet_aton(src_ip)
        dst_b   = _socket.inet_aton(dst_ip)
        ip_hdr  = struct.pack('!BBHHHBBH4s4s',
                              0x45,      # version + IHL
                              0,         # DSCP
                              ip_len,
                              0,         # ID
                              0,         # flags + fragment offset
                              64,        # TTL
                              17,        # protocol: UDP
                              0,         # checksum (let Wireshark recompute)
                              src_b, dst_b)

        frame       = ip_hdr + udp_hdr + payload
        frame_len   = len(frame)

        # pcap packet header
        self._f.write(struct.pack(_PACKET_HDR_FMT,
                                  ts_sec, ts_usec, frame_len, frame_len))
        self._f.write(frame)
        self._f.flush()

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Capture-aware server wrapper ──────────────────────────────────────────────

def serve_with_capture(host: str = '127.0.0.1',
                        port: int = 9999,
                        output_dir: str = 'received',
                        pcap_path: str = 'capture.pcap',
                        loss_rate: float = 0.0,
                        log_path: str = 'logs/pcap_srv.csv') -> dict:
    """
    Like server.serve_once() but also writes every received datagram to a .pcap.
    Import and call from experiments or CLI.
    """
    import random
    from protocol import parse_data, parse_fin, build_ack, build_fin_ack
    from logger import Logger
    import hashlib, os

    os.makedirs(output_dir, exist_ok=True)
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(None)

    received    = {}
    total       = None
    client_addr = None
    start_time  = None
    stats       = dict(acks_sent=0, duplicates=0)

    with PcapWriter(pcap_path) as pcap, Logger(log_path) as logger:
        print(f'[PCAP-SRV] Listening on {host}:{port}  capture→{pcap_path}')
        while True:
            raw, addr = sock.recvfrom(65535)
            ts = time.time()

            # Write to pcap
            pcap.write_packet(raw, src_ip=addr[0], dst_ip=host,
                              src_port=addr[1], dst_port=port, ts=ts)

            if random.random() < loss_rate:
                continue

            fin_md5 = parse_fin(raw)
            if fin_md5 is not None and addr == client_addr:
                ok = False
                if total and len(received) == total:
                    data       = b''.join(received[i] for i in range(total))
                    actual_md5 = hashlib.md5(data).hexdigest()
                    ok         = (actual_md5 == fin_md5)
                    out = os.path.join(output_dir,
                                       f'pcap_file_{int(ts)}.bin')
                    with open(out, 'wb') as f:
                        f.write(data)
                    print(f'[PCAP-SRV] File saved: {out}  ok={ok}')
                sock.sendto(build_fin_ack(ok), addr)
                # write ACK to pcap too
                pcap.write_packet(build_fin_ack(ok), src_ip=host,
                                  dst_ip=addr[0], src_port=port,
                                  dst_port=addr[1], ts=time.time())
                stats.update(ok=ok, duration=time.time()-start_time,
                             packets=len(received))
                break

            result = parse_data(raw)
            if result is None:
                continue

            seq, pkt_total, payload = result

            if client_addr is None:
                client_addr = addr
                total       = pkt_total
                start_time  = ts
                sock.settimeout(30)
                print(f'[PCAP-SRV] Transfer from {addr}  total={total}')

            ack = build_ack(seq)
            sock.sendto(ack, addr)
            pcap.write_packet(ack, src_ip=host, dst_ip=addr[0],
                              src_port=port, dst_port=addr[1], ts=time.time())
            stats['acks_sent'] += 1

            if seq in received:
                stats['duplicates'] += 1
            else:
                received[seq] = payload

    sock.close()
    print(f'[PCAP-SRV] Capture written to {pcap_path}  '
          f'– open in Wireshark (filter: udp.port=={port})')
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe PCAP capture server')
    p.add_argument('--host',  default='127.0.0.1')
    p.add_argument('--port',  default=9999, type=int)
    p.add_argument('--out',   default='received')
    p.add_argument('--pcap',  default='capture.pcap')
    p.add_argument('--loss',  default=0.0, type=float)
    a = p.parse_args()

    import argparse as _ap
    serve_with_capture(a.host, a.port, a.out, a.pcap, a.loss)
