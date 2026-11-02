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
                if result.get("ok") is not True or result.get("matchGuid") != guid:
                    raise ValueError("Endpoint did not acknowledge the match")
                with self.store.db:
                    self.store.db.execute("UPDATE matches SET synced=1 WHERE guid=?", (guid,))
                print(f"Google Sheets synchronized: YES ({guid})", flush=True)
            except Exception as exc:
                # Never log credentials or response bodies.
                print(f"Google Sheets pending ({guid}): {type(exc).__name__}; retrying later", flush=True)
                break
