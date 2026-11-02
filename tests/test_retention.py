import gzip
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fdg.retention import Retention, WireCapture
from fdg.storage import Store
from fdg.engine import Collector
from fdg.identity import Identities


class RetentionTests(unittest.TestCase):
    def setUp(self):
        Path('data').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='data')
        self.store = Store(self.temp.name)
        self.now = time.time()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def save(self, guid, timestamp, synced):
        self.store.save({'match':{'MatchGuid':guid,'Timestamp':timestamp},
                         'players':[{'PrimaryId':'Steam|test|0'}]})
        with self.store.db:
            self.store.db.execute('UPDATE matches SET synced=? WHERE guid=?',(synced,guid))

    def test_expiry_preserves_pending_and_deduplicates_archived_matches(self):
        self.save('old-synced','2000-01-01T00:00:00+00:00',1)
        self.save('old-pending','2000-01-01T00:00:00+00:00',0)
        from fdg.storage import utcnow
        self.save('recent',utcnow(),1)
        Retention(self.store).run(self.now)
        self.assertIsNone(self.store.get('old-synced'))
        self.assertTrue(self.store.exists('old-synced'))
        self.assertIsNotNone(self.store.get('old-pending'))
        self.assertIsNotNone(self.store.get('recent'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM players WHERE guid=?',('old-synced',)).fetchone()[0],0)
        self.assertFalse(self.store.save({'match':{'MatchGuid':'old-synced'},'players':[]}))
        engine=Collector(self.store,Identities(self.temp.name))
        engine.feed({'Event':'UpdateState','Data':{'MatchGuid':'old-synced'}})
        self.assertIsNone(self.store.get('old-synced'))

    def capture(self, name, age, size=10):
        path=self.store.directory/'raw'/name
        path.write_bytes(b'x'*size)
        os.utime(path,(self.now-age,self.now-age))
        return path

    def test_raw_age_quota_and_current_writer_protection(self):
        expired=self.capture('wire-1.bin.gz',8*86400)
        oldest=self.capture('wire-2.bin.gz',300)
        newer=self.capture('wire-3.bin.gz',200)
        active=self.capture('wire-4.bin.gz',1)
        unrelated=self.capture('notes.gz',8*86400)
        Retention(self.store,raw_mb=20/1024/1024).run(self.now)
        self.assertFalse(expired.exists())
        self.assertFalse(oldest.exists())
        self.assertTrue(newer.exists())
        self.assertTrue(active.exists())
        self.assertTrue(unrelated.exists())

    def test_abandoned_checkpoints_expire_but_valid_endings_remain(self):
        self.store.checkpoint('abandoned',{'first_seen':'2000-01-01T00:00:00+00:00'})
        self.store.checkpoint('ended',{'first_seen':'2000-01-01T00:00:00+00:00','winner':0})
        Retention(self.store).run(self.now)
        self.assertEqual(set(self.store.restore()),{'ended'})

    def test_wire_rotation_preserves_received_bytes(self):
        with WireCapture(self.store.directory/'raw',chunk_bytes=8) as capture:
            capture.write(b'12345678')
            capture.write(b'abcdefgh')
        paths=sorted((self.store.directory/'raw').glob('wire-*'))
        self.assertEqual(len(paths),2)
        self.assertEqual(b''.join(gzip.decompress(p.read_bytes()) for p in paths),b'12345678abcdefgh')
