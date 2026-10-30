#!/usr/bin/env python3
"""
A shared cache of ESPN's scoreboard for every built-in league the Nuvio + IPTV app fetches
straight from ESPN itself today. One run of this script (every 5 minutes) does the asking that
every installed TV used to do on its own; the app reads these files first and only falls back to
asking ESPN directly for a league this cache doesn't have, or a game it needs sooner than this
cache refreshes.

This script does NOT parse ESPN's answers. It only caches the raw JSON text, one day at a time,
exactly as ESPN returns it. The app already knows how to read that shape (it asks for the same
thing today); caching the bytes rather than re-deriving anything from them is what keeps this
script simple and keeps the two sides of the cache (what's written, what's read) from drifting
apart as ESPN's fields change.

Files (each written only when its content changed):
  espn/<league id, slashes to underscores>.json
    {"source": "ESPN (site.api.espn.com), unofficial", "id": "<league id>",
     "days": {"<yyyyMMdd>": {"fetchedAt": <epoch ms>, "raw": "<ESPN's scoreboard JSON, as text>"}}}

Covers yesterday to a week ahead (nine days), for every league in espn-leagues.txt that goes
straight to ESPN's plain scoreboard endpoint. Yesterday/today/tomorrow refresh often (minutes);
the four-day to week-ahead window refreshes every few hours — plenty for a week-ahead schedule,
which doesn't move the way a live score does. Leagues the app routes through HockeyTech, the MLB
Stats API, or ESPN's cricket score panel (SportsMatcher.kt's OtherFeeds) are left out of
espn-leagues.txt on purpose: they don't use this endpoint shape, and duplicating their own fetch
logic here would be a second place for it to drift from the app's.

Settings: none. No API key — ESPN's scoreboard is the same unauthenticated endpoint the app
already calls. (Unlike TheSportsDB, there's no published rate limit; this script still paces its
own requests and keeps a time budget so one run can't run away.)

Only the Python standard library is used.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import datetime as dt

ESPN = "https://site.api.espn.com/apis/site/v2/sports/"
LEAGUES_FILE = "espn-leagues.txt"
OUT_DIR = "espn"
BUDGET_SECONDS = 12 * 60
STARTED = time.time()
GAP = 0.5
# How stale a cached day is allowed to get before it's asked for again.
TODAY_TTL = 8 * 60
EDGE_TTL = 45 * 60  # yesterday, tomorrow
FAR_TTL = 5 * 60 * 60  # two days ahead to a week ahead
LIVE_TTL = 90

_last = [0.0]


def log(msg):
    print(msg, flush=True)


def time_left():
    return BUDGET_SECONDS - (time.time() - STARTED)


def get(url):
    """One request, paced, retried a few times. None on failure; never raises."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "application/json",
    }
    for attempt in range(3):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # ESPN turns this down for every league if asked for a range of days; a single
                # day is the only shape this script ever asks for, so a 400 means something else
                # is wrong (an unknown league path) and retrying won't help.
                log("  %s: HTTP 400" % url.split("?")[0])
                return None
            if e.code >= 500 or e.code == 429:
                time.sleep(8)
                continue
            log("  %s: HTTP %s" % (url.split("?")[0], e.code))
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log("  %s: %s" % (url.split("?")[0], type(e).__name__))
            time.sleep(4)
    return None


def load_leagues():
    out = []
    with open(LEAGUES_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            lid, path = parts[0].strip(), parts[1].strip()
            query = parts[2].strip() if len(parts) > 2 else ""
            if lid and path:
                out.append({"id": lid, "path": path, "query": query})
    return out


def safe(lid):
    return re.sub(r"[^a-zA-Z0-9]+", "_", lid)


def eastern_days(now):
    """(day string, category) for yesterday to a week ahead, in US Eastern — the same days ESPN
    groups games by. "today" and "edge" (yesterday, tomorrow) are what the app's Hub keeps warm
    by default; "far" (two days ahead to a week ahead) is the week-ahead window a followed or
    pinned league's row, and Browse All, need."""
    # A fixed UTC-4/5 offset would drift on a DST change; this script runs often enough (every
    # 5 minutes) that being off by an hour on the one or two days a year DST changes is a
    # trivial, self-correcting inaccuracy, not worth a timezone dependency for.
    offset = dt.timedelta(hours=-4)
    local = now + offset
    out = []
    for d in range(-1, 8):
        day = (local + dt.timedelta(days=d)).strftime("%Y%m%d")
        category = "today" if d == 0 else "edge" if d in (-1, 1) else "far"
        out.append((day, category))
    return out


def has_live_or_soon(raw, now):
    """A crude, dependency-free peek at ESPN's own JSON: is anything live, or starting within the
    next 30 minutes? Good enough to decide how urgently to re-ask; the app does the real parsing."""
    if not raw:
        return False
    if re.search(r'"state"\s*:\s*"in"', raw):
        return True
    for m in re.finditer(r'"date"\s*:\s*"([^"]+)"', raw):
        try:
            start = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if dt.timedelta(0) <= (start - now) <= dt.timedelta(minutes=30):
            return True
    return False


def load_existing(lid):
    path = os.path.join(OUT_DIR, safe(lid) + ".json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("days", {})
    except (ValueError, OSError):
        return {}


def write_if_changed(path, obj):
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def due(day_info, category, now_ms):
    if day_info is None:
        return True
    age = now_ms - day_info.get("fetchedAt", 0)
    if day_info.get("liveOrSoon"):
        return age > LIVE_TTL * 1000
    if category == "today":
        return age > TODAY_TTL * 1000
    if category == "edge":
        return age > EDGE_TTL * 1000
    return age > FAR_TTL * 1000


def run():
    now = dt.datetime.now(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    days = eastern_days(now)  # [(yesterday, "edge"), (today, "today"), ..., (+7, "far")]
    leagues = load_leagues()
    # Spread coverage across runs rather than always starting from the same end of the list:
    # a rotating start point means a slow or budget-cut run still gets to every league eventually.
    rotate = int(now.timestamp() // 300) % max(len(leagues), 1)
    leagues = leagues[rotate:] + leagues[:rotate]
    os.makedirs(OUT_DIR, exist_ok=True)
    changed = asked = 0
    skipped_budget = 0
    for lg in leagues:
        if time_left() < 5:
            skipped_budget += 1
            continue
        existing = load_existing(lg["id"])
        out_days = dict(existing)
        touched = False
        for d, category in days:
            info = existing.get(d)
            if not due(info, category, now_ms):
                continue
            url = "%s%s/scoreboard?dates=%s&limit=1000%s" % (ESPN, lg["path"], d, lg["query"])
            raw = get(url)
            asked += 1
            if raw is None:
                continue
            out_days[d] = {
                "fetchedAt": now_ms,
                "raw": raw,
                "liveOrSoon": has_live_or_soon(raw, now),
            }
            touched = True
        if touched:
            path = os.path.join(OUT_DIR, safe(lg["id"]) + ".json")
            if write_if_changed(path, {"source": "ESPN (site.api.espn.com), unofficial", "id": lg["id"], "days": out_days}):
                changed += 1
    log("ESPN shared cache: %d leagues asked for, %d files changed, %d skipped on time budget" % (asked, changed, skipped_budget))
    return changed > 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    run()
