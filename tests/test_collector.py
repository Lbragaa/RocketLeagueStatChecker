import json
import tempfile
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

from fdg.engine import Collector
from fdg.identity import Identities, NAMES
from fdg.storage import Store
from fdg.sync import Sync
from fdg.transport import JsonStream

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def state(playlist=3):
    return {"Event": "UpdateState", "Data": {"MatchGuid": "match-1", "Game": {
        "PlaylistId": playlist, "Arena": "Stadium_P", "bReplay": False,
        "Teams": [{"TeamNum": 0, "Score": 4}, {"TeamNum": 1, "Score": 2}]},
        "Players": [{"Name": n, "PrimaryId": f"Steam|{i}|0", "TeamNum": 0, "Shortcut": i+1,
                     "Score": 100+i, "Goals": 1, "Assists": 2, "Saves": 3,
                     "Shots": 4, "Touches": 20, "CarTouches": 2, "Demos": 1}
                    for i, n in enumerate(NAMES)]}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        Path('data').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='data')
        self.store = Store(self.temp.name)
        self.ids = Identities(self.temp.name)
        self.ids.confirmed = {n: f"Steam|{i}|0" for i,n in enumerate(NAMES)}
        self.now = 100
        self.engine = Collector(self.store, self.ids, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def event(self, name, **data):
        self.engine.feed({"Event": name, "Data": {"MatchGuid": "match-1", **data}})

    def end(self):
        self.event("MatchEnded", WinnerTeamNum=0)
        self.event("PodiumStart")
        self.now += 9
        self.engine.flush()

    def payload(self):
        row = self.store.db.execute("SELECT payload FROM matches").fetchone()
        return json.loads(row[0]) if row else None

    def test_final_stats_unicode_overtime_and_dedup(self):
        s = state()
        self.engine.feed(s)
        self.event("ClockUpdatedSeconds", bOvertime=True, TimeSeconds=12)
        self.event("BallHit", Players=[{"Name":NAMES[0],"Shortcut":1,"TeamNum":0}])
        self.event("MatchEnded", WinnerTeamNum=0)
        s["Data"]["Players"][0]["Score"] = 650
        self.engine.feed(s)
        self.event("PodiumStart")
        self.assertIsNone(self.payload())
        self.now += 9
        self.engine.flush()
        p = self.payload()
        self.assertEqual(p["players"][0]["Score"], 650)
        self.assertEqual(p["players"][2]["Name"], "✪ Marinho")
        self.assertTrue(p["match"]["Overtime"])
        self.assertEqual(p["match"]["TeamScore"], 4)
        self.assertEqual(p["players"][0]["ObservedEvents"]["BallHit"],1)
        self.engine.feed(s)
        self.end()
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM players").fetchone()[0],3)

    def test_excluded_playlists(self):
        for playlist in (1,2,10,11,6,22):
            with self.subTest(playlist=playlist):
                self.engine.feed(state(playlist))
                self.end()
                self.assertIsNone(self.payload())

    def test_missing_or_opposing_teammate(self):
        for opposite in (False,True):
            s=state()
            if opposite: s["Data"]["Players"][2]["TeamNum"]=1
            else: s["Data"]["Players"].pop()
            self.engine.feed(s)
            self.end()
            self.assertIsNone(self.payload())

    def test_name_changes_use_ids(self):
        s=state(13)
        s["Data"]["Players"][2]["Name"]="renamed"
        self.engine.feed(s)
        self.end()
        self.assertIsNotNone(self.payload())

    def test_forfeit_and_disconnect_restart(self):
        self.engine.feed(state())
        self.event("MatchEnded", WinnerTeamNum=1)
        self.engine = Collector(self.store,self.ids,clock=lambda:self.now)
        self.now += 9
        self.engine.flush()
        self.assertEqual(self.payload()["match"]["Result"],"LOSS")

    def test_abandoned_not_saved(self):
        self.engine.feed(state())
        self.event("MatchDestroyed")
        self.assertIsNone(self.payload())

    def test_replays_rejected_goal_replays_allowed(self):
        self.event("ReplayCreated", FileName="replay")
        self.engine.feed(state())
        self.end()
        self.assertIsNone(self.payload())
        self.engine.feed(state())
        self.event("GoalReplayStart")
        s=state(); s["Data"]["Game"]["bReplay"]=True
        self.engine.feed(s)
        self.event("GoalReplayEnd")
        self.engine.feed(state())
        self.end()
        self.assertIsNotNone(self.payload())

    def test_replay_only_fields_rejected(self):
        s=state(); s["Data"]["Game"]["Frame"]=123
        self.engine.feed(s); self.end()
        self.assertIsNone(self.payload())

    def test_casual_test_random_teammates(self):
        self.ids.confirmed={NAMES[0]:"Steam|0|0"}
        self.engine.mode="casual-test"
        s=state()
        for i in (1,2):
            s["Data"]["Players"][i].update(Name=f"Random {i}",PrimaryId=f"Epic|random{i}|0")
        self.engine.feed(s); self.end()
        self.assertEqual(self.payload()["match"]["Mode"],"casual-test")

    def test_casual_test_rejects_ranked(self):
        self.engine.mode="casual-test"
        self.engine.feed(state(13)); self.end()
        self.assertIsNone(self.payload())

    def test_missing_fields_stay_missing(self):
        s=state(); del s["Data"]["Players"][0]["Touches"]
        self.engine.feed(s); self.end()
        self.assertNotIn("Touches",self.payload()["players"][0])

    def test_unconfirmed_names_are_not_trusted(self):
        self.ids.confirmed={}
        self.engine.feed(state()); self.end()
        self.assertIsNone(self.payload())

    def test_invalid_winner_and_missing_scores(self):
        self.engine.feed(state())
        self.event("MatchEnded",WinnerTeamNum=255)
        self.event("MatchDestroyed")
        self.assertIsNone(self.payload())
        s=state(); s["Data"]["Game"]["Teams"].pop()
        self.engine.feed(s); self.end()
        self.assertIsNone(self.payload())

    def test_goal_replay_event_totals_are_excluded(self):
        self.engine.feed(state())
        self.event("GoalReplayStart")
        self.event("GoalScored",Scorer={"Name":NAMES[0],"Shortcut":1,"TeamNum":0})
        self.event("GoalReplayEnd")
        self.event("CrossbarHit",BallLastTouch={"Player":{"Name":NAMES[0],"Shortcut":1,"TeamNum":0}})
        self.event("StatfeedEvent",EventName="Save",MainTarget={"Name":NAMES[0],"Shortcut":1,"TeamNum":0})
        self.end()
        self.assertNotIn("GoalScored",self.payload()["match"]["ObservedEvents"])
        self.assertEqual(self.payload()["players"][0]["ObservedEvents"],{"CrossbarHit":1,"StatfeedEvent:Save":1})

    def test_real_local_tcp_and_http_pipeline(self):
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        received=[]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                received.append(json.loads(handler.rfile.read(int(handler.headers['Content-Length']))))
                handler.send_response(200); handler.end_headers()
                handler.wfile.write(b'{"ok":true,"matchGuid":"match-1"}')

            def log_message(self,*args):
                pass

        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen()
            def send():
                with listener.accept()[0] as connection:
                    messages=[state(),{"Event":"MatchEnded","Data":{"MatchGuid":"match-1","WinnerTeamNum":0}},
                              {"Event":"MatchDestroyed","Data":{"MatchGuid":"match-1"}}]
                    for message in messages:
                        connection.sendall((json.dumps(message,ensure_ascii=False)+'\x00').encode('utf-8'))
            sender=threading.Thread(target=send); sender.start()
            decoder=JsonStream()
            with socket.create_connection(listener.getsockname(),timeout=3) as connection:
                while chunk:=connection.recv(47):
                    for message,original in decoder.feed(chunk):
                        self.engine.feed(message,original)
            sender.join(timeout=3)
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever); thread.start()
        try:
            Sync(self.store,f'http://127.0.0.1:{server.server_port}/exec','local-test').run()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
        self.assertEqual(len(received),1)
        self.assertEqual(len(received[0]['players']),3)
        self.assertEqual(self.store.db.execute('SELECT synced FROM matches').fetchone()[0],1)

    def test_identity_discovery_confirmation(self):
        ids=Identities(self.temp.name)
        ids.discover(state()["Data"]["Players"])
        self.assertFalse(ids.confirmed)
        ids.confirm(NAMES[2],"Steam|2|0")
        self.assertEqual(Identities(self.temp.name).confirmed[NAMES[2]],"Steam|2|0")

    def test_sync_failure_retry_restart(self):
        self.engine.feed(state()); self.end()
        sync=Sync(self.store,"https://example.test/exec","secret")
        with patch("urllib.request.urlopen",side_effect=OSError("offline")):
            sync.run()
        self.assertEqual(self.store.db.execute("SELECT synced FROM matches").fetchone()[0],0)
        self.store.close(); self.store=Store(self.temp.name)
        sync=Sync(self.store,"https://example.test/exec","secret")
        import io
        with patch("urllib.request.urlopen",return_value=io.BytesIO(b'{"ok":true,"matchGuid":"match-1"}')) as request:
            sync.run()
            body=json.loads(request.call_args.args[0].data)
            self.assertEqual(body["match"]["MatchGuid"],"match-1")
        self.assertEqual(self.store.db.execute("SELECT synced FROM matches").fetchone()[0],1)

    def test_raw_preserves_unknown_events(self):
        self.event("FutureEvent", Nested={"unknown":"✪"})
        import gzip
        raw="".join(gzip.open(p,"rt",encoding="utf-8").read() for p in (self.store.directory/"raw").glob("*.jsonl.gz"))
        self.assertIn("FutureEvent",raw)
        self.assertIn("✪",raw)


class TransportTests(unittest.TestCase):
    def test_live_exporter_string_data(self):
        source=state()
        encoded={"Event":source["Event"],"Data":json.dumps(source["Data"],ensure_ascii=False)}
        wire=json.dumps(encoded,ensure_ascii=False)
        result=JsonStream().feed(wire.encode('utf-8'))
        self.assertEqual(result[0][0],source)
        self.assertEqual(result[0][1],wire)

    def test_recovery_unfinished_gzip(self):
        import gzip
        from fdg.transport import read_capture
        with tempfile.TemporaryDirectory(dir='data') as directory:
            path=Path(directory)/'capture.gz'
            with gzip.open(path,'wb') as output:
                output.write(json.dumps({"Event":"UpdateState","Data":json.dumps(state()['Data'])}).encode())
                output.flush()
                self.assertEqual(list(read_capture(path))[0][0],state())

    def test_fragmented_utf8_and_joined_messages(self):
        stream=JsonStream()
        original=json.dumps(state(),ensure_ascii=False)
        wire=(original+"\x00\n"+original).encode()
        received=[]
        for byte in wire:
            received.extend(stream.feed(bytes([byte])))
        self.assertEqual(len(received),2)
        self.assertEqual(received[0][0],state())


if __name__ == '__main__':
    unittest.main()
