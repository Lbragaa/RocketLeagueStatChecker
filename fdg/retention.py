"""Bound debug captures and age out synchronized local payloads."""
import gzip
import json
import time
import re
import sqlite3
from datetime import datetime


class WireCapture:
    def __init__(self, directory, chunk_bytes=16 * 1024 * 1024):
        self.directory, self.chunk_bytes = directory, chunk_bytes
        self.stream = None
        self.size = 0

    def __enter__(self):
        return self

    def write(self, chunk):
        if self.stream is None or self.size + len(chunk) > self.chunk_bytes:
            if self.stream:
                self.stream.close()
            self.stream = gzip.open(self.directory / f"wire-{time.time_ns()}.bin.gz", "wb")
            self.size = 0
        self.stream.write(chunk)
        self.size += len(chunk)

    def flush(self):
        if self.stream:
            self.stream.flush()

    def __exit__(self, *args):
        if self.stream:
            self.stream.close()


class Retention:
    def __init__(self, store, raw_days=7, raw_mb=250, match_days=30):
        self.store = store
        self.raw_days, self.raw_bytes, self.match_days = raw_days, raw_mb * 1024 * 1024, match_days
        self.last_run = None

    def run(self, now=None):
        now = time.time() if now is None else now
        if self.last_run is not None and now - self.last_run < 60:
            return
        self.last_run = now
        files = sorted((p for p in (self.store.directory / 'raw').glob('*.gz')
                        if p.is_file() and not p.is_symlink() and
                        re.fullmatch(r'(wire-\d+\.bin|[a-f0-9]{64}\.jsonl|[a-f0-9]{64}\.jsonl-\d+)\.gz', p.name)),
                       key=lambda p:p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            info = path.stat()
            if now - info.st_mtime < 60:
                continue  # Protect current writers; quota allows recent chunks temporarily.
            if now - info.st_mtime > self.raw_days * 86400 or total > self.raw_bytes:
                try:
                    path.unlink()
                    total -= info.st_size
                except OSError:
                    pass
        removed = False
        with self.store.db:
            for guid, text in self.store.db.execute('SELECT guid,payload FROM matches WHERE synced=1').fetchall():
                try:
                    age = now - datetime.fromisoformat(json.loads(text)['match']['Timestamp']).timestamp()
                except (KeyError, ValueError, TypeError):
                    continue
                if age > self.match_days * 86400:
                    self.store.db.execute('INSERT OR IGNORE INTO archived VALUES (?)', (guid,))
                    self.store.db.execute('DELETE FROM players WHERE guid=?', (guid,))
                    self.store.db.execute('DELETE FROM matches WHERE guid=? AND synced=1', (guid,))
                    removed = True
            for guid, text in self.store.db.execute('SELECT guid,state FROM active').fetchall():
                state = json.loads(text)
                try:
                    age = now - datetime.fromisoformat(state['first_seen']).timestamp()
                except (KeyError, ValueError, TypeError):
                    continue
                if age > 7 * 86400 and 'winner' not in state:
                    self.store.db.execute('DELETE FROM active WHERE guid=?', (guid,))
                    removed = True
        if removed:
            try:
                self.store.db.execute('VACUUM')
            except sqlite3.OperationalError:
                pass  # Busy database pages remain reusable; never interrupt capture.
