"""
NetProbe – Test file generator.
Creates test files of various sizes in test_data/.

Usage:
  python generate_test_files.py
"""

import os
import random

FILES = {
    'file_32k.bin':  32  * 1024,
    'file_128k.bin': 128 * 1024,
    'file_256k.bin': 256 * 1024,
    'file_512k.bin': 512 * 1024,
    'file_1m.bin':   1024 * 1024,
    'file_5m.bin':   5   * 1024 * 1024,
}

def generate(out_dir: str = 'test_data'):
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(42)
    for name, size in FILES.items():
        path = os.path.join(out_dir, name)
        with open(path, 'wb') as f:
            remaining = size
            while remaining > 0:
                n = min(65536, remaining)
                f.write(bytes(rng.getrandbits(8) for _ in range(n)))
                remaining -= n
        print(f'  Created: {path}  ({size:,} bytes)')

if __name__ == '__main__':
    print('Generating test files...')
    generate()
    print('Done.')
