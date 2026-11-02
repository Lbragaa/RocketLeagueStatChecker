from collections import Counter
from .storage import utcnow
from .identity import NAMES

PLAYLISTS = {3: "Casual Standard 3v3", 13: "Competitive Standard 3v3"}


class Collector:
    def __init__(self, store, identities, mode="fdg", playlists=(3, 13), settle=8, clock=None):
        import time
        self.store, self.identities, self.mode = store, identities, mode
        self.playlists, self.settle = playlists, settle
        self.clock = clock or time.time
        self.active = store.restore()

    def feed(self, message, original=None):
        self.store.raw(message, original)
        event, data = message.get("Event"), message.get("Data", {})
        guid = data.get("MatchGuid")
        if not guid or self.store.exists(guid):
            return
        s = self.active.setdefault(guid, {"players": {}, "game": {}, "first_seen": utcnow(),
            "events": {}, "player_events": {}, "overtime": False, "live": False, "replay": False,
            "goal_replay": False, "roster": None, "mode": self.mode})
        if event == "ReplayCreated":
            s["replay"] = True
        if event == "GoalReplayStart":
            s["goal_replay"] = True
        if event == "GoalReplayEnd":
            s["goal_replay"] = False
        if event == "UpdateState":
            game = data.get("Game", {})
            s["state_replay"] = bool(game.get("bReplay"))
            # Frame/Elapsed are documented history-replay-only fields.
            if "Frame" in game or "Elapsed" in game:
                s["replay"] = True
            if game.get("bReplay") is False:
                s["live"] = True
            if not game.get("bReplay", False):
                s["game"].update(game)
                current = data.get("Players", [])
                self.identities.discover(current)
                for p in current:
                    if p.get("PrimaryId"):
                        s["players"].setdefault(p["PrimaryId"], {}).update(p)
                s["overtime"] |= bool(game.get("bOvertime"))
                roster = self.select(current, s)
                if roster:
                    s["roster"] = roster
        if event == "ClockUpdatedSeconds":
            s["overtime"] |= bool(data.get("bOvertime"))
        if event == "MatchEnded" and type(data.get("WinnerTeamNum")) is int and data["WinnerTeamNum"] in (0, 1):
            s["winner"] = data["WinnerTeamNum"]
            s.setdefault("ended", self.clock())
            s.setdefault("ended_at", utcnow())
        if event == "PodiumStart":
            s["podium"] = True
        if event in ("BallHit", "GoalScored", "CrossbarHit", "StatfeedEvent", "BoostPickup"):
            if not s["goal_replay"] and not s.get("state_replay") and not s["replay"] and not data.get("bReplay", False):
                counts = Counter(s["events"])
                counts[event] += 1
                s["events"] = dict(counts)
                targets = data.get("Players", []) if event == "BallHit" else [
                    data.get("Scorer") if event == "GoalScored" else
                    data.get("BallLastTouch", {}).get("Player") if event == "CrossbarHit" else
                    data.get("MainTarget") if event == "StatfeedEvent" else data.get("Player")]
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    matches = [p for p in s["players"].values() if
                        p.get("TeamNum") == target.get("TeamNum") and
                        p.get("Shortcut") == target.get("Shortcut") and
                        p.get("Name") == target.get("Name")]
                    if len(matches) == 1:
                        pc = s["player_events"].setdefault(matches[0]["PrimaryId"], {})
                        label = event + (":" + str(data.get("EventName", "unknown")) if event == "StatfeedEvent" else "")
                        pc[label] = pc.get(label, 0) + 1
        self.store.checkpoint(guid, s)
        if event == "MatchDestroyed":
            self.finalize(guid)
        self.flush()

    def select(self, current, s):
        if s["mode"] == "casual-test":
            anchor = self.identities.confirmed.get(NAMES[0])
            me = [p for p in current if p.get("PrimaryId") == anchor] if anchor else []
            if len(me) != 1:
                return None
            chosen = [p for p in current if p.get("TeamNum") == me[0].get("TeamNum")]
            if len(chosen) != 3:
                return None
        else:
            ids = [self.identities.confirmed.get(n) for n in NAMES]
            if not all(ids) or len(set(ids)) != 3:
                return None
            chosen = [p for p in current if p.get("PrimaryId") in ids]
            if len(chosen) != 3:
                return None
        if len({p.get("TeamNum") for p in chosen}) != 1 or chosen[0].get("TeamNum") not in (0, 1):
            return None
        if len({p.get("PrimaryId") for p in chosen}) != 3 or not all(p.get("PrimaryId") for p in chosen):
            return None
        return {"ids": [p["PrimaryId"] for p in chosen], "team": chosen[0]["TeamNum"]}

    def flush(self, force=False):
        for guid, s in list(self.active.items()):
            if "ended" in s and (force or self.clock() - s["ended"] >= self.settle):
                self.finalize(guid)

    def finalize(self, guid):
        s = self.active.pop(guid)
        game = s["game"]
        reason = None
        allowed = (3,) if s["mode"] == "casual-test" else self.playlists
        if "winner" not in s:
            reason = "no valid MatchEnded (incomplete match)"
        elif s["replay"] or not s["live"]:
            reason = "history replay or no observed live state"
        elif game.get("PlaylistId") not in allowed:
            reason = "excluded playlist"
        elif not s["roster"]:
            reason = "confirmed roster missing or on different teams"
        teams = {t.get("TeamNum"): t.get("Score") for t in game.get("Teams", [])}
        if not reason and not all(type(teams.get(t)) is int for t in (0, 1)):
            reason = "missing final team scores"
        if reason:
            print(f"Ignored {guid}: {reason}", flush=True)
            self.store.forget(guid)
            return
        team = s["roster"]["team"]
        players = [dict(s["players"][pid], ObservedEvents=s["player_events"].get(pid, {})) for pid in s["roster"]["ids"]]
        match = {"MatchGuid": guid, "Timestamp": s["ended_at"], "FirstSeen": s["first_seen"],
            "PlaylistId": game["PlaylistId"], "PlaylistName": PLAYLISTS[game["PlaylistId"]],
            "Arena": game.get("Arena"), "BlueScore": teams[0], "OrangeScore": teams[1],
            "TeamScore": teams[team], "OpponentScore": teams[1-team], "WinnerTeamNum": s["winner"],
            "Result": "WIN" if s["winner"] == team else "LOSS", "Overtime": s["overtime"],
            "DurationSeconds": None, "ObservedEvents": s["events"], "Mode": s["mode"]}
        if self.store.save({"match": match, "players": players}):
            print(f"\n{'FDG' if s['mode'] == 'fdg' else 'CASUAL TEST'} MATCH COMPLETED — {match['Result']} {teams[team]}-{teams[1-team]}")
            for p in players:
                print(f"{p.get('Name')}  {p.get('Score', '?')} pts | {p.get('Goals', '?')} G | {p.get('Assists', '?')} A | {p.get('Saves', '?')} S")
            print("Saved locally: YES | Google Sheets: pending", flush=True)
