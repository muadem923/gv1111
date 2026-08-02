import importlib.util
import os
import tempfile
import time
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scan", ROOT / "livextv_scanner.py")
scan = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scan
spec.loader.exec_module(scan)

class TestScanner(unittest.TestCase):
    def test_api_rows(self):
        self.assertEqual(len(scan.api_rows({"success": True, "data": [{"id": 1}]})), 1)
        self.assertEqual(scan.api_rows({"data": {}}), [])

    def test_source_pairs(self):
        rows = [{"id":"m1","title":"A vs B","category":"football","sources":[{"source":"delta","id":"s1"}]}]
        pairs = scan.source_pairs(rows)
        self.assertEqual(pairs[0]["source"], "delta")
        self.assertEqual(pairs[0]["source_id"], "s1")

    def test_candidate(self):
        p = {"match_id":"m","title":"T","category":"c","source":"admin","source_id":"x"}
        c = scan.candidate_from_row(p, {"streamNo":2,"language":"English","hd":True,"embedUrl":"https://embed.st/embed/admin/x/2"})
        self.assertIsNotNone(c)
        self.assertEqual(c.stream_no, 2)
        self.assertTrue(c.hd)

    def test_render_m3u_headers(self):
        e = scan.Entry("k","m","A vs B","football","admin","x",1,"English",True,"https://embed.st/e","https://cdn/x.m3u8","https://embed.st/","UA",1,["h264","aac"])
        text = scan.render_m3u([e])
        self.assertIn("#EXTVLCOPT:http-referrer=https://embed.st/", text)
        self.assertIn("#EXTVLCOPT:http-user-agent=UA", text)
        self.assertIn("https://cdn/x.m3u8", text)

    def test_last_good_filters_missing_live_match(self):
        now = int(time.time())
        row = scan.Entry("k","old","Old","football","a","x",1,"",False,"https://embed.st/e","https://cdn/x.m3u8",scan.REFERER,scan.UA,now,["h264"])
        merged, reused = scan.merge_last_good([], {"entries":[scan.asdict(row)]}, {"new"}, True)
        self.assertEqual(reused, 0)
        self.assertEqual(merged, [])


    def test_last_good_drops_when_live_api_returns_zero_matches(self):
        now = int(time.time())
        row = scan.Entry("k","old","Old","football","a","x",1,"",False,"https://embed.st/e","https://cdn/x.m3u8",scan.REFERER,scan.UA,now,["h264"])
        merged, reused = scan.merge_last_good([], {"entries":[scan.asdict(row)]}, set(), True)
        self.assertEqual(reused, 0)
        self.assertEqual(merged, [])

    def test_last_good_reuses_on_api_failure(self):
        now = int(time.time())
        row = scan.Entry("k","old","Old","football","a","x",1,"",False,"https://embed.st/e","https://cdn/x.m3u8",scan.REFERER,scan.UA,now,["h264"])
        merged, reused = scan.merge_last_good([], {"entries":[scan.asdict(row)]}, set(), False)
        self.assertEqual(reused, 1)
        self.assertEqual(len(merged), 1)

    def test_redact_secure_url(self):
        s = scan.redact_url("https://x/secure/SECRET/abc/playlist.m3u8")
        self.assertNotIn("SECRET", s)
        self.assertIn("/secure/<", s)

if __name__ == "__main__":
    unittest.main()
