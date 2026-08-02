import importlib.util
import os
import tempfile
import time
import unittest
from unittest.mock import patch
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

    def test_browser_launch_kwargs(self):
        old = scan.BROWSER_CHANNEL
        try:
            scan.BROWSER_CHANNEL = "chrome"
            self.assertEqual(scan.browser_launch_kwargs().get("channel"), "chrome")
            scan.BROWSER_CHANNEL = "chromium"
            self.assertNotIn("channel", scan.browser_launch_kwargs())
        finally:
            scan.BROWSER_CHANNEL = old


    def test_capture_ffprobes_secure_request_without_response(self):
        secure = "https://lb.test/secure/TOKEN/live/playlist.m3u8"

        class FakeRequest:
            url = secure
            method = "GET"
            resource_type = "media"
            headers = {"referer": scan.REFERER, "user-agent": scan.UA}

        class FakeNavResponse:
            status = 200

        class FakeLocator:
            def count(self): return 0
            def is_visible(self): return False

        class FakePage:
            def __init__(self): self.handlers = {}
            def on(self, name, fn): self.handlers[name] = fn
            def goto(self, *_a, **_kw):
                # Reproduce the GitHub v0.1.1 case: secure M3U8 REQUEST is seen,
                # but Playwright never emits a matching response event.
                self.handlers["request"](FakeRequest())
                return FakeNavResponse()
            def wait_for_timeout(self, _ms): pass
            def locator(self, _selector):
                class First:
                    first = FakeLocator()
                return First()
            def title(self): return "embed"
            def content(self): return "<html></html>"
            def evaluate(self, _js): return {"ua": scan.UA, "webdriver": False, "platform": "Linux"}
            @property
            def url(self): return "https://embed.st/embed/test"
            def close(self): pass

        class FakeBrowser:
            def new_page(self): return FakePage()

        c = scan.Candidate("k", "m", "T", "football", "admin", "x", 1, "", True, "https://embed.st/embed/test")
        with patch.object(scan, "ffprobe_verify", return_value=(True, ["h264", "aac"], "")) as fp:
            url, headers, codecs, events = scan.capture_m3u8(c, FakeBrowser())
        self.assertEqual(url, secure)
        self.assertEqual(codecs, ["h264", "aac"])
        fp.assert_called_once_with(secure)
        ff = [e for e in events if "ffprobe" in e][-1]
        self.assertTrue(ff["request_seen"])
        self.assertFalse(ff["response_seen"])
        self.assertIsNone(ff["browser_status"])
        self.assertEqual(ff["trigger"], "request")

    def test_redact_secure_url(self):
        s = scan.redact_url("https://x/secure/SECRET/abc/playlist.m3u8")
        self.assertNotIn("SECRET", s)
        self.assertIn("/secure/<", s)

    def test_match_epoch_seconds_ms(self):
        self.assertEqual(scan.match_epoch_seconds({"date": 1700000000000}), 1700000000)

    def test_select_nearby_matches(self):
        at = 1700000000
        old_before = scan.NEARBY_WINDOW_BEFORE_SECONDS
        old_after = scan.NEARBY_WINDOW_AFTER_SECONDS
        old_max = scan.NEARBY_MAX_MATCHES
        try:
            scan.NEARBY_WINDOW_BEFORE_SECONDS = 3600
            scan.NEARBY_WINDOW_AFTER_SECONDS = 3600
            scan.NEARBY_MAX_MATCHES = 5
            rows = [
                {"id":"live","date":at*1000,"sources":[{"source":"a","id":"1"}]},
                {"id":"near-past","date":(at-300)*1000,"sources":[{"source":"a","id":"2"}]},
                {"id":"near-future","date":(at+120)*1000,"sources":[{"source":"a","id":"3"}]},
                {"id":"far","date":(at+7200)*1000,"sources":[{"source":"a","id":"4"}]},
            ]
            picked = scan.select_nearby_matches(rows, {"live"}, at=at)
            self.assertEqual([x["id"] for x in picked], ["near-past", "near-future"])
            self.assertTrue(all(x.get("_discovery") == "nearby_all" for x in picked))
        finally:
            scan.NEARBY_WINDOW_BEFORE_SECONDS = old_before
            scan.NEARBY_WINDOW_AFTER_SECONDS = old_after
            scan.NEARBY_MAX_MATCHES = old_max

    def test_source_pairs_preserves_discovery(self):
        rows = [{"id":"m1","title":"A","_discovery":"nearby_all","sources":[{"source":"delta","id":"s1"}]}]
        self.assertEqual(scan.source_pairs(rows)[0]["discovery"], "nearby_all")

    def test_classify_upstream_dead_404(self):
        events = [{"ffprobe": False, "error": "Server returned 404 Not Found", "browser_status": 404}]
        self.assertEqual(scan.classify_probe(events, False), "upstream_dead")

    def test_classify_client_restricted_403(self):
        events = [{"ffprobe": False, "error": "Server returned 403 Forbidden", "browser_status": 200}]
        self.assertEqual(scan.classify_probe(events, False), "client_restricted")

    def test_classify_player_no_media(self):
        events = [{"response":"fetch", "status":200}]
        self.assertEqual(scan.classify_probe(events, False), "player_no_media")

    def test_classify_verified(self):
        self.assertEqual(scan.classify_probe([], True), "verified")

if __name__ == "__main__":
    unittest.main()
