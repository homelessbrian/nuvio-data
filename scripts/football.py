#!/usr/bin/env python3
"""
Non-league football for the Nuvio + IPTV Sports page: English leagues ESPN doesn't cover (the
National League and the leagues below it), from TheSportsDB. The app only ever reads the files
this writes, so your TheSportsDB key stays in this repo's secrets.

Two modes:
  python scripts/football.py           Full: every chosen league's season (fixtures, results,
                                       teams). Run once a day.
  python scripts/football.py --scores  Scores: today's games only, for leagues with a game on.
                                       Run every 15 minutes at match times.

Files written (only when something changed):
  football/index.json        The leagues and their teams (for Pick Your Teams).
  football/<league id>.json  A league's games from six weeks ago to the end of the season.

Settings (Settings > Secrets and variables > Actions):
  TSDB_KEY            Secret. Your TheSportsDB key. Needed: the free key can't read whole seasons.
  FOOTBALL_LEAGUES    Variable, optional. Extra TheSportsDB league ids to include, e.g. "4500,4501".
  FOOTBALL_SKIP       Variable, optional. League ids to leave out.
  FOOTBALL_LOGOS      Variable, optional. League ids whose club badges you've checked the licence
                      of, or "all". Badges are left out otherwise (the app shows a coloured tile).

Only the Python standard library is used.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY = (os.environ.get("TSDB_KEY") or "").strip() or "123"
FREE = KEY == "123"
BASE = "https://www.thesportsdb.com/api/v1/json/%s/" % KEY
LIVE_URL = "https://www.thesportsdb.com/api/v2/json/livescore/soccer"
OUT_DIR = "football"
GAP = [0.7 if not FREE else 3.5]
KEEP_DAYS_BACK = 45

# English leagues below League Two (ESPN covers League Two and above).
NONLEAGUE = re.compile(r"national league|southern|isthmian|northern premier", re.I)
NOT_THESE = re.compile(r"women|u21|u23|u18|youth|cup|trophy|vase|shield|reserve", re.I)

_last = [0.0]


def log(msg):
    print(msg, flush=True)


def get(path, v2=False):
    """One request, spaced out and retried. None on failure. The key never appears in output."""
    url = LIVE_URL if v2 else BASE + path
    headers = {"User-Agent": "nuvio-data/1.0 (GitHub Actions)"}
    if v2:
        headers["X-API-KEY"] = KEY
    for attempt in range(4):
        wait = GAP[0] - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                body = r.read().decode("utf-8").strip()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                GAP[0] = min(GAP[0] + 1.5, 8.0)
                log("  rate limited: waiting a minute")
                time.sleep(65)
                continue
            if e.code >= 500:
                time.sleep(10)
                continue
            log("  %s: HTTP %s" % ("livescore" if v2 else path.split("?")[0], e.code))
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log("  %s: %s" % ("livescore" if v2 else path.split("?")[0], type(e).__name__))
            time.sleep(5)
    return None


def env_ids(name):
    return [s.strip() for s in (os.environ.get(name) or "").split(",") if s.strip()]


def short_name(name):
    n = re.sub(r"^English\s+", "", name or "", flags=re.I)
    if re.search(r"national league", n, re.I):
        rest = re.sub(r"national league", "", n, flags=re.I).strip()
        return ("NL " + rest[:1].upper()).strip() if rest else "NL"
    words = [w for w in re.split(r"[\s\-]+", n) if w and w.lower() not in ("league", "division", "football", "the", "of")]
    return "".join(w[0].upper() for w in words)[:5] or n[:5].upper()


def clean_name(name):
    return re.sub(r"^English\s+", "", (name or "").strip(), flags=re.I)


# ------------------------------------------------------------------ games

FINISHED = {"ft", "aet", "pen", "match finished", "after pen.", "after extra time", "finished", "ap", "fin"}
OFF = {"pst", "postponed", "canc", "cancelled", "canceled", "abd", "abandoned", "susp", "suspended", "awd", "wo"}
LIVE = {"1h", "2h", "ht", "et", "bt", "p", "live", "in play", "first half", "second half", "half time", "break time", "int"}


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def start_of(e):
    stamp = (e.get("strTimestamp") or "").strip()
    date = (e.get("dateEvent") or "").strip()
    tm = (e.get("strTime") or "").strip()
    if stamp:
        s = stamp.replace(" ", "T")[:19]
        has_time = True
    elif date and tm and tm[:5] != "00:00":
        s = "%sT%s" % (date, tm[:8])
        has_time = True
    elif date:
        s = "%sT00:00:00" % date
        has_time = False
    else:
        return None, False
    if len(s) == 16:
        s += ":00"
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S"), has_time
    except ValueError:
        return None, False


def state_of(status, hs, as_, start, now):
    st = (status or "").strip().lower()
    if st in OFF:
        return "off"
    if st in FINISHED:
        return "post"
    if st in LIVE or re.match(r"^\d{1,3}('|\+)", st):
        return "in"
    if hs is not None and as_ is not None and start is not None:
        return "post" if now - start > dt.timedelta(hours=2, minutes=15) else "in"
    return "pre"


def norm_event(e, now):
    home, away = (e.get("strHomeTeam") or "").strip(), (e.get("strAwayTeam") or "").strip()
    if not home or not away:
        return None
    start, has_time = start_of(e)
    if start is None:
        return None
    hs, as_ = to_int(e.get("intHomeScore")), to_int(e.get("intAwayScore"))
    status = (e.get("strStatus") or "").strip()
    state = state_of(status, hs, as_, start, now)
    out = {
        "id": str(e.get("idEvent") or ""),
        "home": home, "homeId": str(e.get("idHomeTeam") or home),
        "away": away, "awayId": str(e.get("idAwayTeam") or away),
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hasTime": has_time,
        "state": state,
    }
    if state in ("in", "post") and hs is not None and as_ is not None:
        out["hs"], out["as"] = hs, as_
    progress = (e.get("strProgress") or "").strip()
    if state == "in":
        out["status"] = (progress + "'") if progress.isdigit() else (status.upper() if status else "LIVE")
    elif state == "off":
        out["status"] = "Postponed" if "p" in status.lower()[:1] else (status or "Off")
    rnd = to_int(e.get("intRound"))
    if rnd:
        out["round"] = rnd
    venue = (e.get("strVenue") or "").strip()
    if venue:
        out["venue"] = venue
    return out if out["id"] else None


def season_now(today):
    y = today.year if today.month >= 7 else today.year - 1
    return "%d-%d" % (y, y + 1)


# ------------------------------------------------------------------ full run

def find_leagues(summary):
    chosen = {}
    rows = (get("search_all_leagues.php?c=England&s=Soccer") or {})
    rows = rows.get("countries") or rows.get("leagues") or []
    english = []
    for r in rows:
        lid, name = str(r.get("idLeague") or ""), (r.get("strLeague") or "")
        if not lid:
            continue
        english.append("%s (%s)" % (name, lid))
        if NONLEAGUE.search(name) and not NOT_THESE.search(name):
            chosen[lid] = name
    for lid in env_ids("FOOTBALL_LEAGUES"):
        chosen.setdefault(lid, "")
    for lid in env_ids("FOOTBALL_SKIP"):
        chosen.pop(lid, None)
    summary += ["", "<details><summary>All English leagues on TheSportsDB (%d)</summary>" % len(english), "",
                "; ".join(english) or "none returned", "", "</details>"]
    return chosen


def full_run():
    summary = ["## Non-league football (full)", ""]
    if FREE:
        summary.append("No TSDB_KEY secret: the free key can't read whole seasons, so nothing was done.")
        log(summary[-1])
        return summary
    now = dt.datetime.utcnow()
    today = now.date()
    keep_from = (now - dt.timedelta(days=KEEP_DAYS_BACK)).strftime("%Y-%m-%d")
    logos = {s.lower() for s in env_ids("FOOTBALL_LOGOS")}
    leagues = find_leagues(summary)
    log("Leagues: %s" % ", ".join("%s %s" % (k, v) for k, v in leagues.items()))
    summary[2:2] = ["| League | Id | Games kept | Upcoming | Teams | Badges |", "|---|---|---|---|---|---|"]
    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for lid, name in leagues.items():
        info = ((get("lookupleague.php?id=%s" % lid) or {}).get("leagues") or [{}])[0] or {}
        name = info.get("strLeague") or name or lid
        season = (info.get("strCurrentSeason") or "").strip() or season_now(today)
        log("Reading %s (%s), season %s..." % (name, lid, season))
        rows = (get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(season))) or {}).get("events") or []
        if not rows:
            rows = ((get("eventspastleague.php?id=%s" % lid) or {}).get("events") or []) + \
                   ((get("eventsnextleague.php?id=%s" % lid) or {}).get("events") or [])
        events = {}
        for e in rows:
            ev = norm_event(e, now)
            if ev and ev["start"][:10] >= keep_from:
                events[ev["id"]] = ev
        events = sorted(events.values(), key=lambda x: (x["start"], x["home"]))
        teams = {}
        for ev in events:
            teams[ev["homeId"]] = ev["home"]
            teams[ev["awayId"]] = ev["away"]
        badges = {}
        use_logos = "all" in logos or lid in logos
        if use_logos:
            for t in (get("lookup_all_teams.php?id=%s" % lid) or {}).get("teams") or []:
                b = (t.get("strBadge") or t.get("strTeamBadge") or "").strip()
                if b.startswith("https://") and t.get("idTeam"):
                    badges[str(t["idTeam"])] = b
        team_list = [dict({"id": tid, "name": tn}, **({"badge": badges[tid]} if tid in badges else {}))
                     for tid, tn in sorted(teams.items(), key=lambda kv: kv[1].lower())]
        league_badge = (info.get("strBadge") or "").strip() if use_logos else ""
        upcoming = sum(1 for e in events if e["state"] == "pre")
        summary.insert(-6, "| %s | %s | %d | %d | %d | %s |" % (clean_name(name), lid, len(events), upcoming, len(teams),
                                                               "yes" if use_logos else "no"))
        # No games on TheSportsDB for this one: left out of the app (it would be an empty league).
        if not events:
            continue
        write_if_changed(os.path.join(OUT_DIR, "%s.json" % lid), {"league": lid, "events": events})
        index.append({
            "id": lid, "name": clean_name(name), "short": short_name(name), "season": season,
            "badge": league_badge or None, "teams": team_list, "games": len(events), "upcoming": upcoming,
        })
    summary.insert(-6, "")
    summary.insert(-6, "Leagues with no games on TheSportsDB are left out of the app.")
    if index:
        write_if_changed(os.path.join(OUT_DIR, "index.json"), {"source": "TheSportsDB (thesportsdb.com)", "leagues": index})
    else:
        summary.append("")
        summary.append("No leagues found, so nothing was changed.")
    return summary


# ------------------------------------------------------------------ scores run

def scores_run():
    summary = ["## Non-league football (scores)", ""]
    if FREE:
        summary.append("No TSDB_KEY secret: skipped.")
        return summary
    path = os.path.join(OUT_DIR, "index.json")
    if not os.path.exists(path):
        summary.append("No football/index.json yet: run the full update first.")
        return summary
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    now = dt.datetime.utcnow()
    files = {}
    busy = []
    for lg in index.get("leagues") or []:
        p = os.path.join(OUT_DIR, "%s.json" % lg["id"])
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        files[lg["id"]] = (p, data)
        for ev in data.get("events") or []:
            try:
                start = dt.datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%SZ")
            except (KeyError, ValueError):
                continue
            if ev.get("state") == "in" or (ev.get("state") == "pre" and start - dt.timedelta(minutes=20) <= now <= start + dt.timedelta(hours=3)):
                busy.append(lg["id"])
                break
    if not busy:
        summary.append("No games on right now.")
        log(summary[-1])
        return summary
    log("Games on in: %s" % ", ".join(busy))
    updates = {}
    days = {now.strftime("%Y-%m-%d")}
    if now.hour < 3:
        days.add((now - dt.timedelta(days=1)).strftime("%Y-%m-%d"))
    for lid in busy:
        for d in sorted(days):
            for e in (get("eventsday.php?d=%s&l=%s" % (d, lid)) or {}).get("events") or []:
                ev = norm_event(e, now)
                if ev:
                    updates[ev["id"]] = ev
    live = get("", v2=True) or {}
    live_rows = live.get("livescore") or live.get("events") or []
    n_live = 0
    for e in live_rows:
        if str(e.get("idLeague") or "") not in files:
            continue
        ev = norm_event(e, now)
        if not ev:
            continue
        if ev["state"] == "pre":
            ev["state"] = "in"
            ev["status"] = "LIVE"
        n_live += 1
        old = updates.get(ev["id"], {})
        updates[ev["id"]] = dict(old, **ev)
    changed = 0
    for lid, (p, data) in files.items():
        evs = data.get("events") or []
        touched = False
        for i, ev in enumerate(evs):
            u = updates.get(ev.get("id"))
            if not u:
                continue
            merged = dict(ev)
            for k in ("state", "status", "hs", "as", "start", "hasTime"):
                if k in u:
                    merged[k] = u[k]
            if merged.get("state") not in ("in", "off"):
                merged.pop("status", None)
            if merged != ev:
                evs[i] = merged
                touched = True
                changed += 1
        if touched:
            write_if_changed(p, data)
    summary.append("Checked %d league(s); live feed had %d of our games; %d game(s) changed." % (len(busy), n_live, changed))
    log(summary[-1])
    return summary


# ------------------------------------------------------------------ files

def write_if_changed(path, obj):
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def write_summary(lines):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    lines = scores_run() if "--scores" in sys.argv else full_run()
    write_summary(lines)
