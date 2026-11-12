import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import livextv_scanner as sc


def make_stream(sid=1, name="NFL Network", always_live=0, starts=0, ends=0, subs=()):
    return {
        "id": sid,
        "name": name,
        "always_live": always_live,
        "starts_at": starts,
        "ends_at": ends,
        "iframe": f"https://embed.example/embed/{name.lower().replace(' ', '-')}",
        "uri_name": name.lower().replace(" ", "-"),
        "source_tag": "HD | something",
        "substreams": list(subs),
    }


def make_sub(sub_id=101, uri="nfl-network_540p"):
    return {"id": sub_id, "uri_name": uri, "iframe": f"https://embed.example/embed/{uri}", "source_tag": "SD | x"}


class FakeResponse:
    def __init__(self, obj, status=200):
        self._obj = obj
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"status {self.status}")

    def json(self):
        return self._obj


class FakeSession:
    def __init__(self, obj, status=200):
        self._resp = FakeResponse(obj, status)

    def get(self, url, timeout=None):
        return self._resp


class TestScanner(unittest.TestCase):
    def test_stream_categories(self):
        self.assertEqual(sc.stream_categories({"streams": [{"category": "A"}, "x"]}), [{"category": "A"}])
        self.assertEqual(sc.stream_categories(None), [])
        self.assertEqual(sc.stream_categories({"data": []}), [])

    def test_is_live_now(self):
        now = 1_000_000
        self.assertTrue(sc.is_live_now(make_stream(always_live=1), now))
        self.assertFalse(sc.is_live_now(make_stream(starts=now + 60), now))
        self.assertFalse(sc.is_live_now(make_stream(starts=now - 100, ends=now - 2000), now))
        self.assertTrue(sc.is_live_now(make_stream(starts=now - 100, ends=now - 10), now))
        self.assertTrue(sc.is_live_now(make_stream(starts=now - 100, ends=now + 100), now))
        self.assertTrue(sc.is_live_now(make_stream(starts=now - 3600), now))
        self.assertFalse(sc.is_live_now(make_stream(starts=now - 999999), now))

    def test_quality_of(self):
        self.assertEqual(sc.quality_of({"uri_name": "nfl-network_540p"}), "540p")
        self.assertEqual(sc.quality_of({"uri_name": "x", "source_tag": "HD | NFL"}), "HD")
        self.assertEqual(sc.quality_of({"uri_name": "x", "source_tag": "whatever"}), "")

    def test_referer_for(self):
        self.assertEqual(sc.referer_for("https://embed.example/embed/a"), "https://embed.example/")
        with patch.object(sc, "REFERER_OVERRIDE", "https://fixed.example/"):
            self.assertEqual(sc.referer_for("https://embed.example/embed/a"), "https://fixed.example/")

    def test_discover_candidates(self):
        now = sc.now_ts()
        live = make_stream(sid=1, always_live=1, subs=[make_sub(101), make_sub(102, "nfl-network_720p")])
        upcoming = make_stream(sid=2, starts=now + 3600)
        obj = {"success": True, "streams": [{"category": "American Football", "streams": [live, upcoming]}]}
        cands, n_live, ok, errs = sc.discover_candidates(FakeSession(obj))
        self.assertTrue(ok)
        self.assertEqual(errs, [])
        self.assertEqual(n_live, 1)
        self.assertEqual([c.key for c in cands], ["1|0", "1|101", "1|102"])
        self.assertEqual(cands[1].quality, "540p")
        self.assertEqual(cands[0].category, "American Football")

    def test_discover_candidates_api_failure(self):
        cands, n_live, ok, errs = sc.discover_candidates(FakeSession({}, status=503))
        self.assertFalse(ok)
        self.assertEqual(cands, [])
        self.assertEqual(len(errs), 1)

    def test_discover_candidates_caps(self):
        now = sc.now_ts()
        streams = [make_stream(sid=i, always_live=1, subs=[make_sub(i * 10 + 1), make_sub(i * 10 + 2, f"s{i}_720p")]) for i in range(10)]
        obj = {"streams": [{"category": "A", "streams": streams}]}
        with patch.object(sc, "MAX_STREAMS", 2), patch.object(sc, "MAX_EMBEDS", 3):
            cands, n_live, ok, _ = sc.discover_candidates(FakeSession(obj))
        self.assertEqual(n_live, 2)
        self.assertEqual(len(cands), 3)

    def test_redact_secure_url(self):
        u = "https://lb1.example/secure/TOKEN123/rtmp/stream/x/1/playlist.m3u8"
        r = sc.redact_url(u)
        self.assertNotIn("TOKEN123", r)
        self.assertIn("/secure/<", r)
        self.assertTrue(r.endswith("/playlist.m3u8"))

    def test_classify_verified(self):
        self.assertEqual(sc.classify_probe([], True), "verified")

    def test_classify_upstream_dead_404(self):
        ev = [{"ffprobe": False, "error": "Server returned 404 Not Found"}]
        self.assertEqual(sc.classify_probe(ev, False), "upstream_dead")

    def test_classify_client_restricted_403(self):
        ev = [{"response": "media", "status": 403}]
        self.assertEqual(sc.classify_probe(ev, False), "client_restricted")

    def test_classify_player_no_media(self):
        self.assertEqual(sc.classify_probe([{"page": {"status": 200}}], False), "player_no_media")

    def test_classify_html_media_counts_as_media(self):
        ev = [{"html_media": "https://x/playlist.m3u8"}, {"ffprobe": False, "error": "timeout"}]
        self.assertEqual(sc.classify_probe(ev, False), "transport_timeout")

    def _entry(self, key="1|0", verified_at=None):
        return sc.Entry(
            key=key, title="T", category="C", quality="HD", embed_url="https://e.example/x",
            url="https://m.example/x.m3u8", referer="https://e.example/", user_agent="UA",
            verified_at=sc.now_ts() if verified_at is None else verified_at, codecs=["h264"],
        )

    def test_last_good_reuses_on_api_failure(self):
        prev = {"entries": [sc.asdict(self._entry())]}
        final, reused = sc.merge_last_good([], prev, set(), api_ok=False)
        self.assertEqual(reused, 1)
        self.assertEqual(len(final), 1)

    def test_last_good_drops_expired(self):
        old = self._entry(verified_at=sc.now_ts() - sc.LAST_GOOD_TTL_SECONDS - 10)
        final, reused = sc.merge_last_good([], {"entries": [sc.asdict(old)]}, set(), api_ok=False)
        self.assertEqual(reused, 0)
        self.assertEqual(final, [])

    def test_last_good_drops_missing_when_api_ok(self):
        prev = {"entries": [sc.asdict(self._entry(key="gone|0"))]}
        final, reused = sc.merge_last_good([], prev, {"1|0"}, api_ok=True)
        self.assertEqual(reused, 0)

    def test_last_good_keeps_current_key_when_api_ok(self):
        prev = {"entries": [sc.asdict(self._entry(key="1|0"))]}
        final, reused = sc.merge_last_good([], prev, {"1|0"}, api_ok=True)
        self.assertEqual(reused, 1)

    def test_entry_name(self):
        self.assertEqual(sc.entry_name(self._entry()), "T • HD")

    def test_render_m3u_headers(self):
        text = sc.render_m3u([self._entry()])
        self.assertTrue(text.startswith("#EXTM3U\n"))
        self.assertIn('#EXTVLCOPT:http-referrer=https://e.example/', text)
        self.assertIn("#EXTVLCOPT:http-user-agent=UA", text)
        self.assertIn("https://m.example/x.m3u8", text)
        self.assertIn('group-title="LiveXTV"', text)

    def test_browser_launch_kwargs(self):
        with patch.object(sc, "BROWSER_CHANNEL", "chrome"):
            self.assertEqual(sc.browser_launch_kwargs(), {"headless": True, "channel": "chrome"})
        with patch.object(sc, "BROWSER_CHANNEL", "chromium"):
            self.assertEqual(sc.browser_launch_kwargs(), {"headless": True})


if __name__ == "__main__":
    unittest.main()