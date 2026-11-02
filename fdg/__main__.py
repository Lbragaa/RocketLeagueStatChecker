import argparse
import gzip
import os
from pathlib import Path
import socket
import sys
import time

from .engine import Collector
from .identity import Identities
from .storage import Store
from .sync import Sync
from .transport import JsonStream, read_capture


def load_env():
    path = Path(".env")
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def main():
    load_env()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="FDG official Stats API collector (Ctrl+C to stop)")
    parser.add_argument("--mode", choices=("fdg", "casual-test"), default="fdg")
    parser.add_argument("--confirm-id", nargs=2, metavar=("NAME", "PRIMARY_ID"))
    parser.add_argument("--confirm-player", metavar="NAME", help="Confirm a player's sole discovered ID without shell pipe characters")
    parser.add_argument("--recover-wire", metavar="PATH", help="Recover a recorded wire capture, then exit")
    args = parser.parse_args()
    store = Store(os.getenv("FDG_DATA_DIR", "data"))
    identities = Identities(store.directory)
    if args.confirm_player:
        candidates = identities.candidates.get(args.confirm_player, [])
        if len(candidates) != 1:
            store.close()
            parser.error("This player must have exactly one discovered ID; use Python directly with --confirm-id to select among candidates")
        args.confirm_id = (args.confirm_player, candidates[0])
    if args.confirm_id:
        identities.confirm(*args.confirm_id)
        print("Identity confirmed. Restart the collector to use it.")
        store.close()
        return
    engine = Collector(store, identities, args.mode,
                       tuple(int(p) for p in os.getenv("FDG_PLAYLISTS", "3,13").split(",")),
                       settle=float("inf") if args.recover_wire else max(0, float(os.getenv("FDG_SETTLE_SECONDS", "0"))),
                       clock=(lambda: 0) if args.recover_wire else None)
    sync = Sync(store, os.getenv("FDG_SHEETS_URL", ""), os.getenv("FDG_SHEETS_TOKEN", ""))
    if args.recover_wire:
        try:
            for message, original in read_capture(args.recover_wire):
                engine.feed(message, original)
            engine.flush(force=True)
            sync.run()
        finally:
            store.close()
        return
    print(f"FDG collector — {args.mode}. Close this window or press Ctrl+C to stop.", flush=True)
    if not sync.url or not sync.token:
        print("Sheets not configured: matches remain safely queued locally.")
    # Upload runs on its own connection so slow HTTP never blocks receiving final states.
    import threading
    stop = threading.Event()

    def upload_loop():
        upload_store = Store(store.directory)
        uploader = Sync(upload_store, sync.url, sync.token)
        try:
            while not stop.is_set():
                uploader.run()
                stop.wait(30)
        finally:
            upload_store.close()

    worker = threading.Thread(target=upload_loop, daemon=True)
    worker.start()
    host, port = os.getenv("FDG_HOST", "127.0.0.1"), int(os.getenv("FDG_PORT", "49123"))
    wire_path = store.directory / "raw" / f"wire-{time.time_ns()}.bin.gz"
    try:
        with gzip.open(wire_path, "ab") as wire:
            while True:
                try:
                    print(f"Connecting to Rocket League at {host}:{port}…", flush=True)
                    with socket.create_connection((host, port), timeout=3) as conn:
                        conn.settimeout(1)
                        stream = JsonStream()
                        print("Connected. Listening for matches.", flush=True)
                        while True:
                            try:
                                chunk = conn.recv(65536)
                            except socket.timeout:
                                engine.flush()
                                continue
                            if not chunk:
                                raise ConnectionError("Game disconnected")
                            wire.write(chunk)
                            wire.flush()
                            for message, original in stream.feed(chunk):
                                engine.feed(message, original)
                except (OSError, ValueError) as exc:
                    print(f"Disconnected ({type(exc).__name__}). Retrying in 3 seconds…", flush=True)
                    engine.flush()
                    time.sleep(3)
    except KeyboardInterrupt:
        print("\nStopping. Completed matches and pending uploads are stored locally.")
    finally:
        # Preserve the settling window across restarts; do not finalize early on shutdown.
        stop.set()
        worker.join(timeout=16)
        store.close()


if __name__ == "__main__":
    main()
