#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

VERSION = "0.1.0"
HOME = os.getenv("LIVEXTV_HOME", "https://livextv.pro/")
API_BASE = os.getenv("LIVEXTV_API_BASE", "https://livextv-backend.onrender.com/api").rstrip("/")
UA = os.getenv(
    "LIVEXTV_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
)
REFERER = os.getenv("LIVEXTV_MEDIA_REFERER", "https://embed.st/")
OUT_M3U = Path(os.getenv("LIVEXTV_OUTPUT", "livextv.m3u"))
STATE_FILE = Path(os.getenv("LIVEXTV_STATE", "state/livextv_last_good.json"))
REPORT_FILE = Path(os.getenv("LIVEXTV_REPORT", "scan_report.json"))
MAX_MATCHES = int(os.getenv("LIVEXTV_MAX_MATCHES", "30"))
MAX_SOURCES_PER_MATCH = int(os.getenv("LIVEXTV_MAX_SOURCES_PER_MATCH", "3"))
MAX_EMBEDS = int(os.getenv("LIVEXTV_MAX_EMBEDS", "45"))
BROWSER_WAIT_SECONDS = float(os.getenv("LIVEXTV_BROWSER_WAIT_SECONDS", "7"))
BROWSER_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_BROWSER_TIMEOUT_SECONDS", "15"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_HTTP_TIMEOUT_SECONDS", "15"))
FFPROBE_TIMEOUT_SECONDS = int(os.getenv("LIVEXTV_FFPROBE_TIMEOUT_SECONDS", "18"))
FFPROBE_ANALYZE_US = int(os.getenv("LIVEXTV_FFPROBE_ANALYZE_US", "1500000"))
LAST_GOOD_TTL_SECONDS = int(os.getenv("LIVEXTV_LAST_GOOD_TTL_SECONDS", "900"))
FALLBACK_ALL = os.getenv("LIVEXTV_FALLBACK_ALL", "0").lower() in {"1", "true", "yes"}
GROUP_TITLE = os.getenv("LIVEXTV_GROUP_TITLE", "LiveXTV")

SECURE_RE = re.compile(r"(/secure/)([^/]+)(/)", re.I)
MEDIA_RE = re.compile(r"\.m3u8(?:$|\?)", re.I)


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


def api_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, dict) and isinstance(obj.get("data"), list):
        obj = obj["data"]
    if not isinstance(obj, list):
        return []
    return [x for x in obj if isinstance(x, dict)]


def source_pairs(matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for m in matches[:MAX_MATCHES]:
        mid = str(m.get("id") or "").strip()
        title = clean_title(str(m.get("title") or mid))
        category = str(m.get("category") or "").strip()
        sources = m.get("sources") if isinstance(m.get("sources"), list) else []
        for s in sources[:MAX_SOURCES_PER_MATCH]:
            if not isinstance(s, dict):
                continue
            source = str(s.get("source") or "").strip()
            sid = str(s.get("id") or "").strip()
            key = (mid, source, sid)
            if source and sid and key not in seen:
                seen.add(key)
                out.append({"match_id": mid, "title": title, "category": category, "source": source, "source_id": sid})
    return out


def build_stream_url(source: str, source_id: str) -> str:
    return f"{API_BASE}/stream/{urllib.parse.quote(source, safe='')}/{urllib.parse.quote(source_id, safe='')}"


@dataclass
class Candidate:
    key: str
    match_id: str
    title: str
    category: str
    source: str
    source_id: str
    stream_no: int
    language: str
    hd: bool
    embed_url: str


@dataclass
class Entry:
    key: str
    match_id: str
    title: str
    category: str
    source: str
    source_id: str
    stream_no: int
    language: str
    hd: bool
    embed_url: str
    url: str
    referer: str
    user_agent: str
    verified_at: int
    codecs: list[str]


def candidate_from_row(pair: dict[str, str], row: dict[str, Any]) -> Candidate | None:
    embed = str(row.get("embedUrl") or row.get("embed_url") or "").strip()
    if not embed.startswith("http"):
        return None
    try:
        stream_no = int(row.get("streamNo") or row.get("stream_no") or 1)
    except Exception:
        stream_no = 1
    key = f"{pair['match_id']}|{pair['source']}|{pair['source_id']}|{stream_no}"
    return Candidate(
        key=key,
        match_id=pair["match_id"], title=pair["title"], category=pair["category"],
        source=pair["source"], source_id=pair["source_id"], stream_no=stream_no,
        language=clean_title(str(row.get("language") or "")), hd=bool(row.get("hd")), embed_url=embed,
    )


def ffprobe_verify(url: str) -> tuple[bool, list[str], str]:
    exe = shutil.which("ffprobe")
    if not exe:
        return False, [], "ffprobe not found"
    cmd = [
        exe, "-hide_banner", "-v", "error",
        "-rw_timeout", "12000000",
        "-user_agent", UA,
        "-referer", REFERER,
        "-probesize", "131072",
        "-analyzeduration", str(FFPROBE_ANALYZE_US),
        "-show_entries", "stream=codec_name,codec_type",
        "-of", "json", url,
    ]
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
    # Require a real A/V stream; ignore PNG cover/thumbnail-only responses.
    good_video = any(t == "video" and c.lower() not in {"png", "mjpeg", "jpeg"} for t, c in zip(types, codecs))
    good_audio = any(t == "audio" for t in types)
    ok = bool(good_video or good_audio)
    return ok, codecs, "" if ok else "no playable audio/video stream"


def capture_m3u8(candidate: Candidate, browser) -> tuple[str | None, dict[str, str], list[str], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    observed: list[tuple[str, dict[str, str], int]] = []
    page = browser.new_page()

    def on_response(resp):
        url = resp.url
        if not MEDIA_RE.search(url):
            return
        try:
            headers = {str(k).lower(): str(v) for k, v in dict(resp.request.headers).items()}
        except Exception:
            headers = {}
        status = int(resp.status)
        observed.append((url, headers, status))
        events.append({"status": status, "url": redact_url(url), "referer": headers.get("referer", "")})

    page.on("response", on_response)
    try:
        page.goto(candidate.embed_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_SECONDS * 1000)
        deadline = time.time() + BROWSER_WAIT_SECONDS
        while time.time() < deadline:
            if any(s in {200, 206} and "/secure/" in u for u, _h, s in observed):
                break
            page.wait_for_timeout(250)
        if not any(s in {200, 206} and "/secure/" in u for u, _h, s in observed):
            # Light click fallback for players that wait for user gesture.
            for selector in ["button", "[class*=play]", "[aria-label*=play i]"]:
                try:
                    loc = page.locator(selector).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1000)
                        page.wait_for_timeout(1800)
                        break
                except Exception:
                    pass
    except Exception as exc:
        events.append({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        try:
            page.close()
        except Exception:
            pass

    # Prefer secure browser-successful manifests. Test each outside Chromium with ffprobe.
    seen: set[str] = set()
    for url, headers, status in observed:
        if url in seen or status not in {200, 206} or "/secure/" not in url:
            continue
        seen.add(url)
        ok, codecs, err = ffprobe_verify(url)
        events.append({"ffprobe": ok, "url": redact_url(url), "codecs": codecs, "error": err[:300]})
        if ok:
            return url, headers, codecs, events
    return None, {}, [], events


def discover_matches(session: requests.Session) -> tuple[list[dict[str, Any]], bool, list[str]]:
    errors: list[str] = []
    endpoints = ["matches/live"] + (["matches/all"] if FALLBACK_ALL else [])
    api_ok = False
    for ep in endpoints:
        url = f"{API_BASE}/{ep}"
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT_SECONDS)
            r.raise_for_status()
            rows = api_rows(r.json())
            api_ok = True
            if rows:
                return rows, api_ok, errors
            if ep == "matches/live":
                return [], api_ok, errors
        except Exception as exc:
            errors.append(f"{ep}: {type(exc).__name__}: {exc}")
    return [], api_ok, errors


def discover_candidates(session: requests.Session, pairs: list[dict[str, str]]) -> tuple[list[Candidate], list[str]]:
    out: list[Candidate] = []
    errors: list[str] = []
    seen: set[str] = set()
    for pair in pairs:
        try:
            r = session.get(build_stream_url(pair["source"], pair["source_id"]), timeout=HTTP_TIMEOUT_SECONDS)
            r.raise_for_status()
            rows = api_rows(r.json())
        except Exception as exc:
            errors.append(f"stream {pair['source']}/{pair['source_id']}: {type(exc).__name__}: {exc}")
            continue
        for row in rows:
            c = candidate_from_row(pair, row)
            if c and c.key not in seen:
                seen.add(c.key)
                out.append(c)
                if len(out) >= MAX_EMBEDS:
                    return out, errors
    return out, errors


def merge_last_good(current: list[Entry], previous_state: dict[str, Any], live_match_ids: set[str], api_ok: bool) -> tuple[list[Entry], int]:
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
        # If live API succeeded, never resurrect a match that has disappeared from live list.
        if api_ok and e.match_id not in live_match_ids:
            continue
        by_key[e.key] = e
        reused += 1
    return list(by_key.values()), reused


def entry_name(e: Entry) -> str:
    bits = [e.title]
    if e.language:
        bits.append(e.language)
    if e.hd:
        bits.append("HD")
    if e.stream_no > 1:
        bits.append(f"S{e.stream_no}")
    return " • ".join(bits)


def render_m3u(entries: list[Entry]) -> str:
    lines = ["#EXTM3U"]
    for e in sorted(entries, key=lambda x: (x.category, x.title.lower(), x.stream_no, x.source)):
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
    session.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Referer": HOME})
    matches, api_ok, errors = discover_matches(session)
    live_match_ids = {str(m.get("id") or "") for m in matches if m.get("id")}
    pairs = source_pairs(matches)
    candidates, stream_errors = discover_candidates(session, pairs)
    errors.extend(stream_errors)

    print(f"LiveXTV GitHub Scanner v{VERSION}")
    print(f"matches={len(matches)} source_pairs={len(pairs)} embeds={len(candidates)}")

    current: list[Entry] = []
    browser_events: list[dict[str, Any]] = []
    if candidates:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
                context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 800}, ignore_https_errors=False)
                for idx, c in enumerate(candidates, 1):
                    print(f"[{idx}/{len(candidates)}] {c.title} | {c.source} S{c.stream_no}")
                    url, _headers, codecs, events = capture_m3u8(c, context)
                    browser_events.append({"key": c.key, "title": c.title, "embed": c.embed_url, "events": events})
                    if not url:
                        continue
                    current.append(Entry(
                        key=c.key, match_id=c.match_id, title=c.title, category=c.category,
                        source=c.source, source_id=c.source_id, stream_no=c.stream_no,
                        language=c.language, hd=c.hd, embed_url=c.embed_url, url=url,
                        referer=REFERER, user_agent=UA, verified_at=now_ts(), codecs=codecs,
                    ))
                    print(f"  PASS {','.join(codecs)} {redact_url(url)}")
                context.close()
                browser.close()
        except Exception as exc:
            errors.append(f"playwright: {type(exc).__name__}: {exc}")

    previous = load_json(STATE_FILE, {})
    final_entries, reused = merge_last_good(current, previous, live_match_ids, api_ok)

    state = {
        "version": VERSION,
        "updated_at": now_ts(),
        "ttl_seconds": LAST_GOOD_TTL_SECONDS,
        "entries": [asdict(e) for e in final_entries],
    }
    report = {
        "version": VERSION,
        "started_at": int(started),
        "elapsed_seconds": round(time.time() - started, 2),
        "api_ok": api_ok,
        "matches": len(matches),
        "source_pairs": len(pairs),
        "embed_candidates": len(candidates),
        "verified_current": len(current),
        "reused_last_good": reused,
        "published_entries": len(final_entries),
        "entries": [public_entry(e) for e in final_entries],
        "browser_events": browser_events,
        "errors": errors,
    }
    atomic_write(OUT_M3U, render_m3u(final_entries))
    atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    atomic_write(REPORT_FILE, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"verified_current={len(current)} reused={reused} published={len(final_entries)}")
    if errors:
        print(f"warnings/errors={len(errors)}")
        for e in errors[:10]:
            print(" -", e)
    # Do not fail merely because there are no live matches. Fail only on hard API/browser setup failure with candidates.
    if not api_ok and not final_entries:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
