import json
import urllib.request


class Sync:
    def __init__(self, store, url, token):
        self.store, self.url, self.token = store, url, token

    def run(self):
        if not self.url or not self.token:
            return
        for guid, payload in self.store.db.execute("SELECT guid,payload FROM matches WHERE synced=0").fetchall():
            try:
                body = json.dumps({"token": self.token, **json.loads(payload)}, ensure_ascii=False).encode("utf-8")
                request = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.load(response)
                revision = json.loads(payload)["match"].get("Revision", 1)
                if result.get("protocol") != 2:
                    print("Sheets receiver needs updating: redeploy apps_script/Code.gs as a new version.", flush=True)
                    break
                if result.get("ok") is not True or result.get("matchGuid") != guid or result.get("revision") != revision:
                    raise ValueError("Endpoint did not acknowledge this match revision")
                with self.store.db:
                    acknowledged = self.store.db.execute("UPDATE matches SET synced=1 WHERE guid=? AND payload=?", (guid, payload)).rowcount
                status = "YES" if acknowledged else "older revision received; newer statistics queued"
                print(f"Google Sheets synchronized: {status} ({guid})", flush=True)
            except Exception as exc:
                # Never log credentials or response bodies.
                print(f"Google Sheets pending ({guid}): {type(exc).__name__}; retrying later", flush=True)
                break
