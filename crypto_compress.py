"""
NetProbe – Encryption & Compression Support (Bonus)

Drop-in pre/post-processing for file data before it enters the UDP pipeline.

Encryption  : XOR stream cipher with SHA-256-derived keystream (simple, no deps)
Compression : zlib (stdlib)

Usage in client.py:
    from crypto_compress import prepare, recover
    data = prepare(data, mode='compress+encrypt', key='mypassword')
    # ... send over UDP ...
    data = recover(data, mode='compress+encrypt', key='mypassword')

Standalone demo:
    python crypto_compress.py --file test_data/file_32k.bin --key secret
"""

import os
import zlib
import hashlib
import argparse


# ── XOR stream cipher ─────────────────────────────────────────────────────────

def _keystream(key: str, length: int) -> bytes:
    """Deterministic keystream from SHA-256 hash chain."""
    stream = bytearray()
    seed   = hashlib.sha256(key.encode()).digest()
    while len(stream) < length:
        seed   = hashlib.sha256(seed).digest()
        stream.extend(seed)
    return bytes(stream[:length])


def xor_encrypt(data: bytes, key: str) -> bytes:
    ks = _keystream(key, len(data))
    return bytes(a ^ b for a, b in zip(data, ks))


# decrypt == encrypt for XOR
xor_decrypt = xor_encrypt


# ── Compression ───────────────────────────────────────────────────────────────

def compress(data: bytes, level: int = 6) -> bytes:
    return zlib.compress(data, level)


def decompress(data: bytes) -> bytes:
    return zlib.decompress(data)


# ── Combined API ──────────────────────────────────────────────────────────────

def prepare(data: bytes, mode: str = 'compress', key: str = '') -> bytes:
    """
    Transform data before transmission.
    mode options:
      'compress'           – zlib only
      'encrypt'            – XOR cipher only
      'compress+encrypt'   – compress first, then encrypt
      'none' / ''          – pass-through
    """
    if 'compress' in mode:
        data = compress(data)
    if 'encrypt' in mode:
        if not key:
            raise ValueError('Encryption requires a key.')
        data = xor_encrypt(data, key)
    return data


def recover(data: bytes, mode: str = 'compress', key: str = '') -> bytes:
    """Reverse of prepare()."""
    if 'encrypt' in mode:
        if not key:
            raise ValueError('Decryption requires a key.')
        data = xor_decrypt(data, key)
    if 'compress' in mode:
        data = decompress(data)
    return data


# ── Stats helper ──────────────────────────────────────────────────────────────

def compression_ratio(original: bytes, compressed: bytes) -> float:
    return len(original) / len(compressed) if compressed else 0.0


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='NetProbe Crypto/Compression Demo')
    p.add_argument('--file',  required=True)
    p.add_argument('--key',   default='netprobe_secret')
    p.add_argument('--mode',  default='compress+encrypt',
                   choices=['none', 'compress', 'encrypt', 'compress+encrypt'])
    a = p.parse_args()

    with open(a.file, 'rb') as f:
        original = f.read()

    print(f'Original size  : {len(original):,} bytes')

    processed = prepare(original, a.mode, a.key)
    print(f'Processed size : {len(processed):,} bytes  (mode={a.mode})')

    if 'compress' in a.mode:
        ratio = compression_ratio(original, processed if 'encrypt' not in a.mode
                                  else decompress(xor_decrypt(processed, a.key)
                                                  if 'encrypt' in a.mode else processed))
        print(f'Compress ratio : {ratio:.2f}x')

    restored = recover(processed, a.mode, a.key)
    ok = (restored == original)
    print(f'Integrity check: {"PASS" if ok else "FAIL"}')
    print(f'MD5 original   : {hashlib.md5(original).hexdigest()}')
    print(f'MD5 restored   : {hashlib.md5(restored).hexdigest()}')
