import json
from pathlib import Path

NAMES = ("bregzz_", "Moose-", "✪ Marinho")


class Identities:
    def __init__(self, directory):
        self.path = Path(directory) / "identities.json"
        self.candidate_path = Path(directory) / "discovered.json"
        self.confirmed = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.candidates = json.loads(self.candidate_path.read_text(encoding="utf-8")) if self.candidate_path.exists() else {}

    def discover(self, players):
        changed = False
        for player in players:
            name, pid = player.get("Name"), player.get("PrimaryId")
            if name in NAMES and pid and name not in self.confirmed:
                values = self.candidates.setdefault(name, [])
                if pid not in values:
                    values.append(pid)
                    print(f"Discovered {name}: {pid}. Confirm with: .\\start_fdg.bat --confirm-id \"{name}\" \"{pid}\"", flush=True)
                    changed = True
        if changed:
            self.candidate_path.write_text(json.dumps(self.candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    def confirm(self, name, pid):
        if name not in NAMES or pid not in self.candidates.get(name, []):
            raise ValueError("Confirm only a configured name and an ID observed in discovered.json")
        if any(value == pid and key != name for key, value in self.confirmed.items()):
            raise ValueError("This ID is already assigned to another player")
        self.confirmed[name] = pid
        self.path.write_text(json.dumps(self.confirmed, ensure_ascii=False, indent=2), encoding="utf-8")
