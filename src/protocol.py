"""
NetProbe – Application-layer protocol over UDP.

Packet formats (all big-endian):
  DATA    : type(1B) | seq(4B) | total(4B) | payload_len(2B) | crc32(4B) | payload
  ACK     : type(1B) | ack_num(4B) | crc32(4B)
  FIN     : type(1B) | crc32(4B) | md5_hex(32B ascii)
  FIN_ACK : type(1B) | status(1B)   (status: 1=OK, 0=FAIL)
"""

import struct
import zlib

PACKET_TYPE_DATA    = 0x01
PACKET_TYPE_ACK     = 0x02
PACKET_TYPE_FIN     = 0x03
PACKET_TYPE_FIN_ACK = 0x04

_DATA_HDR_FMT  = '!B I I H I'          # 15 bytes
_ACK_FMT       = '!B I I'              #  9 bytes
_FIN_FMT       = '!B I 32s'            # 37 bytes
_FIN_ACK_FMT   = '!B B'               #  2 bytes

DATA_HEADER_SIZE = struct.calcsize(_DATA_HDR_FMT)
ACK_SIZE         = struct.calcsize(_ACK_FMT)
FIN_SIZE         = struct.calcsize(_FIN_FMT)
FIN_ACK_SIZE     = struct.calcsize(_FIN_ACK_FMT)

DEFAULT_CHUNK_SIZE = 1024   # bytes – configurable via CLI
MAX_RETRIES        = 5      # configurable – default documented in report
DEFAULT_TIMEOUT    = 1.0    # seconds


def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# ── DATA ──────────────────────────────────────────────────────────────────────

def build_data(seq: int, total: int, payload: bytes) -> bytes:
    hdr = struct.pack(_DATA_HDR_FMT,
                      PACKET_TYPE_DATA, seq, total, len(payload), _crc(payload))
    return hdr + payload


def parse_data(raw: bytes):
    """Return (seq, total, payload) or None on error / bad checksum."""
    if len(raw) < DATA_HEADER_SIZE:
        return None
    ptype, seq, total, plen, crc = struct.unpack(_DATA_HDR_FMT, raw[:DATA_HEADER_SIZE])
    if ptype != PACKET_TYPE_DATA:
        return None
    payload = raw[DATA_HEADER_SIZE: DATA_HEADER_SIZE + plen]
    if len(payload) != plen or _crc(payload) != crc:
        return None
    return seq, total, payload


# ── ACK ───────────────────────────────────────────────────────────────────────

def build_ack(ack_num: int) -> bytes:
    return struct.pack(_ACK_FMT, PACKET_TYPE_ACK, ack_num,
                       _crc(struct.pack('!I', ack_num)))


def parse_ack(raw: bytes):
    """Return ack_num or None."""
    if len(raw) < ACK_SIZE:
        return None
    ptype, ack_num, crc = struct.unpack(_ACK_FMT, raw[:ACK_SIZE])
    if ptype != PACKET_TYPE_ACK:
        return None
    if _crc(struct.pack('!I', ack_num)) != crc:
        return None
    return ack_num


# ── FIN / FIN-ACK ─────────────────────────────────────────────────────────────

def build_fin(md5_hex: str) -> bytes:
    md5_b = md5_hex.encode()[:32].ljust(32, b'\x00')
    return struct.pack(_FIN_FMT, PACKET_TYPE_FIN, _crc(md5_b), md5_b)


def parse_fin(raw: bytes):
    """Return md5_hex string or None."""
    if len(raw) < FIN_SIZE:
        return None
    ptype, crc, md5_b = struct.unpack(_FIN_FMT, raw[:FIN_SIZE])
    if ptype != PACKET_TYPE_FIN:
        return None
    if _crc(md5_b) != crc:
        return None
    return md5_b.rstrip(b'\x00').decode()


def build_fin_ack(ok: bool) -> bytes:
    return struct.pack(_FIN_ACK_FMT, PACKET_TYPE_FIN_ACK, 1 if ok else 0)


def parse_fin_ack(raw: bytes):
    """Return True / False or None."""
    if len(raw) < FIN_ACK_SIZE:
        return None
    ptype, status = struct.unpack(_FIN_ACK_FMT, raw[:FIN_ACK_SIZE])
    if ptype != PACKET_TYPE_FIN_ACK:
        return None
    return status == 1
