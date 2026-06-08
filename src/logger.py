"""
NetProbe – Event logger.
Writes one CSV row per network event so analyzer.py can later compute metrics.
"""

import csv
import time
import os


class Logger:
    FIELDS = ['timestamp', 'event', 'seq', 'details']

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._f = open(path, 'w', newline='', encoding='utf-8')
        self._w = csv.writer(self._f)
        self._w.writerow(self.FIELDS)
        self._f.flush()

    def log(self, event: str, seq: int = -1, **kwargs):
        self._w.writerow([f'{time.time():.6f}', event, seq, str(kwargs)])
        self._f.flush()

    def close(self):
        self._f.close()

    # context-manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
