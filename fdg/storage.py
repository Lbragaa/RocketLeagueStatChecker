import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        (self.directory / "raw").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "fdg.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS active (guid TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS archived (guid TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS matches (
                guid TEXT PRIMARY KEY, payload TEXT NOT NULL, synced INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS players (
                guid TEXT, primary_id TEXT, stats TEXT NOT NULL,
                PRIMARY KEY(guid, primary_id));
        """)

    def raw(self, message, original=None):
        guid = message.get("Data", {}).get("MatchGuid", "unassigned")
        filename = hashlib.sha256(str(guid).encode()).hexdigest() + ".jsonl.gz"
        path = self.directory / "raw" / filename
        if path.exists() and path.stat().st_size > 16 * 1024 * 1024:
            import time
            path.rename(path.with_name(path.stem + f"-{time.time_ns()}.gz"))
        with gzip.open(path, "at", encoding="utf-8") as stream:
            stream.write(json.dumps({"received_at": utcnow(), "message": message,
                                     "original": original}, ensure_ascii=False) + "\n")

    def checkpoint(self, guid, state):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO active VALUES (?,?)",
                            (guid, json.dumps(state, ensure_ascii=False)))

    def restore(self):
        return {guid: json.loads(state) for guid, state in self.db.execute("SELECT * FROM active")}

    def exists(self, guid):
        return self.db.execute("SELECT 1 FROM matches WHERE guid=? UNION ALL SELECT 1 FROM archived WHERE guid=?", (guid, guid)).fetchone() is not None

    def get(self, guid):
        row = self.db.execute("SELECT payload FROM matches WHERE guid=?", (guid,)).fetchone()
        return json.loads(row[0]) if row else None

    def revise(self, payload):
        guid = payload["match"]["MatchGuid"]
        with self.db:
            old = self.get(guid)
            if not old or old == payload:
                return False
            payload["match"]["Revision"] = old["match"].get("Revision", 1) + 1
            self.db.execute("UPDATE matches SET payload=?, synced=0 WHERE guid=?",
                            (json.dumps(payload, ensure_ascii=False), guid))
            for player in payload["players"]:
                self.db.execute("INSERT OR REPLACE INTO players VALUES (?,?,?)",
                                (guid, player["PrimaryId"], json.dumps(player, ensure_ascii=False)))
        return True

    def save(self, payload):
        guid = payload["match"]["MatchGuid"]
        with self.db:
            if self.exists(guid):
                return False
            payload["match"]["Revision"] = 1
            self.db.execute("INSERT INTO matches(guid,payload) VALUES (?,?)",
                            (guid, json.dumps(payload, ensure_ascii=False)))
            for player in payload["players"]:
                self.db.execute("INSERT INTO players VALUES (?,?,?)",
                                (guid, player["PrimaryId"], json.dumps(player, ensure_ascii=False)))
            self.db.execute("DELETE FROM active WHERE guid=?", (guid,))
        return True

    def forget(self, guid):
        with self.db:
            self.db.execute("DELETE FROM active WHERE guid=?", (guid,))

    def close(self):
        self.db.close()
