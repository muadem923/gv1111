#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

VERSION = "0.2.0"
API_BASE = os.getenv("LIVEXTV_API_BASE", "https://api.ppv.st/api").rstrip("/")
UA = os.getenv(
    "LIVEXTV_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
)
OUT_M3U = Path(os.getenv("LIVEXTV_OUTPUT", "livextv.m3u"))
STATE_FILE = Path(os.getenv("LIVEXTV_STATE", "state/livextv_last_good.json"))
REPORT_FILE = Path(os.getenv("LIVEXTV_REPORT", "scan_report.json"))
MAX_STREAMS = int(os.getenv("LIVEXTV_MAX_MATCHES", "30"))
MAX_SUBSTREAMS = int(os.getenv("LIVEXTV_MAX_SOURCES_PER_MATCH", "2"))
MAX_EMBEDS = int(os.getenv("LIVEXTV_MAX_EMBEDS", "45"))
BROWSER_WAIT_SECONDS = float(os.getenv("LIVEXTV_BROWSER_WAIT_SECONDS", "7"))
BROWSER_CHANNEL = os.getenv("LIVEXTV_BROWSER_CHANNEL", "").strip().lower()
BROWSER_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_BROWSER_TIMEOUT_SECONDS", "15"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_HTTP_TIMEOUT_SECONDS", "15"))
FFPROBE_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_FFPROBE_TIMEOUT_SECONDS", "18"))
FFPROBE_ANALYZE_US = int(os.getenv("LIVEXTV_FFPROBE_ANALYZE_US", "1500000"))
LAST_GOOD_TTL_SECONDS = int(os.getenv("LIVEXTV_LAST_GOOD_TTL_SECONDS", "900"))
LIVE_WINDOW_BEFORE_SECONDS = int(os.getenv("LIVEXTV_LIVE_WINDOW_BEFORE_SECONDS", "10800"))
LIVE_GRACE_AFTER_SECONDS = int(os.getenv("LIVEXTV_LIVE_GRACE_AFTER_SECONDS", "1800"))
REFERER_OVERRIDE = os.getenv("LIVEXTV_MEDIA_REFERER", "").strip()
DRY_RUN = os.getenv("LIVEXTV_DRY_RUN", "0").lower() in {"1", "true", "yes"}
GROUP_TITLE = os.getenv("LIVEXTV_GROUP_TITLE", "LiveXTV")

SECURE_RE = re.compile(r"(/secure/)([^/]+)(/)", re.I)
MEDIA_RE = re.compile(r"\.m3u8(?:$|\?)", re.I)
HTML_MEDIA_RE = re.compile(r"https?://[^\"'<>\\ ]+?\.m3u8(?:\?[^\"'<>\\ ]*)?", re.I)
QUALITY_RE = re.compile(r"(\d{3,4}p)", re.I)


def now_ts() -> int:
    return int(time.time())


def esc_attr(s: str) -> str:
    return str(s or "").replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def redact_url(url: str) -> str:
    return SECURE_RE.sub(lambda m: m.group(1) + "<" + hashlib.sha256(m.group(2).encode()).hexdigest()[:10] + ">" + m.group(3), url or "")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def stream_categories(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, dict) and isinstance(obj.get("streams"), list):
        return [c for c in obj["streams"] if isinstance(c, dict)]
    return []


def is_live_now(row: dict[str, Any], now: int) -> bool:
    if row.get("always_live"):
        return True
    starts = int(row.get("starts_at") or 0)
    ends = int(row.get("ends_at") or 0)
    if starts <= 0 or starts > now:
        return False
    if ends > 0:
        return now <= ends + LIVE_GRACE_AFTER_SECONDS
    return now - starts <= LIVE_WINDOW_BEFORE_SECONDS


def quality_of(variant: dict[str, Any]) -> str:
    m = QUALITY_RE.search(str(variant.get("uri_name") or ""))
    if m:
        return m.group(1).lower()
    tag = str(variant.get("source_tag") or "").split("|")[0].strip().upper()
    return tag if tag in {"HD", "SD", "FHD", "4K"} else ""


def referer_for(embed_url: str) -> str:
    if REFERER_OVERRIDE:
        return REFERER_OVERRIDE
    p = urllib.parse.urlsplit(embed_url)
    return f"{p.scheme}://{p.netloc}/"


@dataclass
class Candidate:
    key: str
    title: str
    category: str
    quality: str
    embed_url: str


@dataclass
class Entry:
    key: str
    title: str
    category: str
    quality: str
    embed_url: str
    url: str
    referer: str
    user_agent: str
    verified_at: int
    codecs: list[str]


def discover_candidates(session: requests.Session) -> tuple[list[Candidate], int, bool, list[str]]:
    try:
        r = session.get(f"{API_BASE}/streams", timeout=HTTP_TIMEOUT_SECONDS)
        r.raise_for_status()
        cats = stream_categories(r.json())
    except Exception as exc:
        return [], 0, False, [f"streams: {type(exc).__name__}: {exc}"]

    live: list[tuple[str, dict[str, Any]]] = []
    now = now_ts()
    for cat in cats:
        category = clean_title(str(cat.get("category") or ""))
        for st in cat.get("streams") or []:
            if isinstance(st, dict) and is_live_now(st, now):
                live.append((category, st))
    live = live[:MAX_STREAMS]

    out: list[Candidate] = []
    seen: set[str] = set()
    for category, st in live:
        variants = [st] + [v for v in (st.get("substreams") or []) if isinstance(v, dict)][:MAX_SUBSTREAMS]
        for idx, v in enumerate(variants):
            embed = str(v.get("iframe") or "").strip()
            if not embed.startswith("http"):
                continue
            key = f"{st.get('id')}|{0 if idx == 0 else (v.get('id') or 0)}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Candidate(
                key=key,
                title=clean_title(str(st.get("name") or st.get("id") or "")),
                category=category,
                quality=quality_of(v),
                embed_url=embed,
            ))
            if len(out) >= MAX_EMBEDS:
                return out, len(live), True, []
    return out, len(live), True, []


def browser_launch_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {"headless": True}
    if BROWSER_CHANNEL and BROWSER_CHANNEL not in {"chromium", "bundled"}:
        kw["channel"] = BROWSER_CHANNEL
    return kw


def replay_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k == "cookie" or k.startswith("x-")}


def ffprobe_verify(url: str, referer: str, extra_headers: dict[str, str] | None = None) -> tuple[bool, list[str], str]:
    exe = shutil.which("ffprobe")
    if not exe:
        return False, [], "ffprobe not found"
    cmd = [
        exe, "-hide_banner", "-v", "error",
        "-rw_timeout", "12000000",
        "-user_agent", UA,
        "-referer", referer,
        "-probesize", "131072",
        "-analyzeduration", str(FFPROBE_ANALYZE_US),
        "-show_entries", "stream=codec_name,codec_type",
        "-of", "json",
    ]
    hdr = replay_headers(extra_headers or {})
    if hdr:
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdr.items())]
    cmd.append(url)
    try:
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=FFPROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False, [], "ffprobe timeout"
    except Exception as exc:
        return False, [], f"{type(exc).__name__}: {exc}"
    if cp.returncode != 0:
        return False, [], (cp.stderr or "")[-500:]
    try:
        obj = json.loads(cp.stdout or "{}")
        streams = obj.get("streams") if isinstance(obj, dict) else []
    except Exception:
        streams = []
    codecs = [str(x.get("codec_name") or "") for x in streams if isinstance(x, dict) and x.get("codec_name")]
    types = [str(x.get("codec_type") or "") for x in streams if isinstance(x, dict)]
    good_video = any(t == "video" and c.lower() not in {"png", "mjpeg", "jpeg"} for t, c in zip(types, codecs))
    good_audio = any(t == "audio" for t in types)
    ok = bool(good_video or good_audio)
    return ok, codecs, "" if ok else "no playable audio/video stream"


def capture_m3u8(candidate: Candidate, browser) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    # Capture media URLs at REQUEST time: runners may never surface a response
    # event even though ffprobe can fetch the same URL directly.
    observed: dict[str, dict[str, Any]] = {}
    page = browser.new_page()
    main_status: int | None = None
    result_url: str | None = None
    result_codecs: list[str] = []
    referer = referer_for(candidate.embed_url)

    def on_request(req):
        u = req.url
        if "/fetch" in u or MEDIA_RE.search(u):
            events.append({
                "request": "fetch" if "/fetch" in u else "media",
                "method": req.method,
                "url": redact_url(u),
                "resource_type": req.resource_type,
            })
        if MEDIA_RE.search(u):
            try:
                headers = {str(k).lower(): str(v) for k, v in dict(req.headers).items()}
            except Exception:
                headers = {}
            row = observed.setdefault(u, {"status": None, "request_seen": False, "response_seen": False})
            row["request_seen"] = True
            if headers:
                row["headers"] = headers

    def on_request_failed(req):
        u = req.url
        if "/fetch" in u or MEDIA_RE.search(u):
            try:
                failure = req.failure
            except Exception:
                failure = None
            events.append({"request_failed": redact_url(u), "failure": str(failure or "")[:300]})

    def on_console(msg):
        if msg.type in {"error", "warning"}:
            events.append({"console": msg.type, "text": str(msg.text)[:500]})

    def on_response(resp):
        url = resp.url
        status = int(resp.status)
        if "/fetch" in url:
            events.append({"response": "fetch", "status": status, "url": redact_url(url)})
            try:
                body = resp.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                events.append({"fetch_body_keys": sorted(str(k) for k in body.keys())})
                hosts = sorted({urllib.parse.urlsplit(v).netloc for v in body.values() if isinstance(v, str) and v.startswith("http")})
                if hosts:
                    events.append({"fetch_url_hosts": hosts})
        if not MEDIA_RE.search(url):
            return
        row = observed.setdefault(url, {"status": None, "request_seen": False, "response_seen": False})
        row["status"] = status
        row["response_seen"] = True
        events.append({"response": "media", "status": status, "url": redact_url(url)})

    page.on("request", on_request)
    page.on("requestfailed", on_request_failed)
    page.on("console", on_console)
    page.on("response", on_response)
    try:
        resp = page.goto(candidate.embed_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_SECONDS * 1000)
        if resp is not None:
            main_status = int(resp.status)
        deadline = time.time() + BROWSER_WAIT_SECONDS
        # Observe the full window: players may retry dead CDN hosts and only
        # surface a working URL on a later request.
        while time.time() < deadline:
            page.wait_for_timeout(250)
        if not observed:
            for selector in ["video", "button", "[class*=play]", "[aria-label*=play i]"]:
                try:
                    loc = page.locator(selector).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1200)
                        page.wait_for_timeout(1800)
                        events.append({"clicked": selector})
                        break
                except Exception:
                    pass
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            html = page.content()
            html_len = len(html)
        except Exception:
            html = ""
            html_len = 0
        # Some embeds inline the playlist URL in page source; use it as a
        # fallback source when the player never fires a media request.
        for u in HTML_MEDIA_RE.findall(html):
            if u not in observed:
                observed.setdefault(u, {"status": None, "request_seen": False, "response_seen": False})
                events.append({"html_media": redact_url(u)})
        events.append({
            "page": {
                "status": main_status,
                "url": page.url,
                "title": title[:200],
                "html_length": html_len,
            }
        })

        for url, meta in observed.items():
            status = meta.get("status")
            headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
            ok, codecs, err = ffprobe_verify(url, referer, headers)
            events.append({
                "ffprobe": ok,
                "url": redact_url(url),
                "codecs": codecs,
                "error": err[:300],
                "browser_status": status,
                "request_seen": bool(meta.get("request_seen")),
                "response_seen": bool(meta.get("response_seen")),
                "has_cookie": bool(headers.get("cookie")),
                "header_names": sorted(headers.keys()),
            })
            if ok:
                result_url = url
                result_codecs = codecs
                break
    except Exception as exc:
        events.append({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        try:
            page.close()
        except Exception:
            pass

    return result_url, result_codecs, events


def classify_probe(events: list[dict[str, Any]], verified: bool) -> str:
    if verified:
        return "verified"
    saw_media = False
    statuses: list[int] = []
    errors: list[str] = []
    for event in events:
        if event.get("request") == "media" or event.get("response") == "media" or "ffprobe" in event or "html_media" in event:
            saw_media = True
        for key in ("status", "browser_status"):
            val = event.get(key)
            if isinstance(val, int):
                statuses.append(val)
        if event.get("error"):
            errors.append(str(event.get("error")))
        if event.get("failure"):
            errors.append(str(event.get("failure")))
    text = " ".join(errors).lower()
    if 404 in statuses or 410 in statuses or re.search(r"\b(404|410)\b", text):
        return "upstream_dead"
    if any(x in statuses for x in (401, 403, 429)) or re.search(r"\b(401|403|429)\b", text):
        return "client_restricted"
    if "timeout" in text or "timed out" in text:
        return "transport_timeout"
    if saw_media:
        return "media_unverified"
    return "player_no_media"


def merge_last_good(current: list[Entry], previous_state: dict[str, Any], current_keys: set[str], api_ok: bool) -> tuple[list[Entry], int]:
    now = now_ts()
    by_key = {e.key: e for e in current}
    reused = 0
    prev_rows = previous_state.get("entries") if isinstance(previous_state, dict) else []
    if not isinstance(prev_rows, list):
        prev_rows = []
    for row in prev_rows:
        if not isinstance(row, dict):
            continue
        try:
            e = Entry(**{k: row[k] for k in Entry.__dataclass_fields__.keys()})
        except Exception:
            continue
        if e.key in by_key:
            continue
        age = now - int(e.verified_at)
        if age < 0 or age > LAST_GOOD_TTL_SECONDS:
            continue
        if api_ok and e.key not in current_keys:
            continue
        by_key[e.key] = e
        reused += 1
    return list(by_key.values()), reused


def entry_name(e: Entry) -> str:
    bits = [e.title]
    if e.quality:
        bits.append(e.quality)
    return " • ".join(bits)


def render_m3u(entries: list[Entry]) -> str:
    lines = ["#EXTM3U"]
    for e in sorted(entries, key=lambda x: (x.category, x.title.lower(), x.quality, x.key)):
        name = entry_name(e)
        lines.append(f'#EXTINF:-1 group-title="{esc_attr(GROUP_TITLE)}" tvg-name="{esc_attr(name)}",{name}')
        lines.append(f"#EXTVLCOPT:http-referrer={e.referer}")
        lines.append(f"#EXTVLCOPT:http-user-agent={e.user_agent}")
        lines.append(e.url)
    return "\n".join(lines) + "\n"


def public_entry(e: Entry) -> dict[str, Any]:
    d = asdict(e)
    d["url"] = redact_url(e.url)
    return d


def main() -> int:
    started = time.time()
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})
    candidates, live_streams, api_ok, errors = discover_candidates(session)

    print(f"LiveXTV GitHub Scanner v{VERSION}")
    print(f"api_ok={api_ok} live_streams={live_streams} embeds={len(candidates)}")

    current: list[Entry] = []
    browser_events: list[dict[str, Any]] = []
    if candidates and not DRY_RUN:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(**browser_launch_kwargs())
                context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, ignore_https_errors=False)
                for idx, c in enumerate(candidates, 1):
                    print(f"[{idx}/{len(candidates)}] {c.title} | {c.quality or 'main'}")
                    url, codecs, events = capture_m3u8(c, context)
                    classification = classify_probe(events, bool(url))
                    browser_events.append({
                        "key": c.key, "title": c.title, "embed": c.embed_url,
                        "classification": classification, "events": events,
                    })
                    if not url:
                        print(f"  {classification.upper()}")
                        continue
                    current.append(Entry(
                        key=c.key, title=c.title, category=c.category, quality=c.quality,
                        embed_url=c.embed_url, url=url, referer=referer_for(c.embed_url),
                        user_agent=UA, verified_at=now_ts(), codecs=codecs,
                    ))
                    print(f"  PASS {','.join(codecs)} {redact_url(url)}")
                context.close()
                browser.close()
        except Exception as exc:
            errors.append(f"playwright: {type(exc).__name__}: {exc}")

    previous = load_json(STATE_FILE, {})
    final_entries, reused = merge_last_good(current, previous, {c.key for c in candidates}, api_ok)

    state = {
        "version": VERSION,
        "updated_at": now_ts(),
        "ttl_seconds": LAST_GOOD_TTL_SECONDS,
        "entries": [asdict(e) for e in final_entries],
    }
    classification_counts: dict[str, int] = {}
    for row in browser_events:
        name = str(row.get("classification") or "unknown")
        classification_counts[name] = classification_counts.get(name, 0) + 1

    report = {
        "version": VERSION,
        "browser_channel": BROWSER_CHANNEL or "bundled-chromium",
        "started_at": int(started),
        "elapsed_seconds": round(time.time() - started, 2),
        "api_ok": api_ok,
        "live_matches": live_streams,
        "embed_candidates": len(candidates),
        "verified_current": len(current),
        "reused_last_good": reused,
        "published_entries": len(final_entries),
        "classification_counts": classification_counts,
        "entries": [public_entry(e) for e in final_entries],
        "browser_events": browser_events,
        "errors": errors,
    }
    atomic_write(OUT_M3U, render_m3u(final_entries))
    atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    atomic_write(REPORT_FILE, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"verified_current={len(current)} reused={reused} published={len(final_entries)}")
    if classification_counts:
        print("classifications=" + json.dumps(classification_counts, ensure_ascii=False, sort_keys=True))
    if errors:
        print(f"warnings/errors={len(errors)}")
        for e in errors[:10]:
            print(" -", e)
    if not api_ok and not final_entries:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())