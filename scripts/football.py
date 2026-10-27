#!/usr/bin/env python3
"""
Non-league football for the Nuvio + IPTV Sports page: English leagues ESPN doesn't cover (the
National League and the leagues below it), from TheSportsDB. Also the other team sports ESPN
doesn't cover (rugby league, cricket, UK ice hockey, Gaelic games, netball): see OTHER below. The app only ever reads the files
this writes, so your TheSportsDB key stays in this repo's secrets.

Two modes:
  python scripts/football.py           Full: every chosen league's season (fixtures, results,
                                       teams). Run once a day.
  python scripts/football.py --scores  Scores: today's games only, for leagues with a game on.
                                       Run every 15 minutes at match times.
  python scripts/football.py --check   Check: reads everything the full run would and reports
                                       how good each league's data is, but writes nothing.

Files written (only when something changed):
  football/index.json        The leagues and their teams (for Pick Your Teams).
  football/<league id>.json  A league's games from six weeks ago to the end of the season, and its
                             table (when TheSportsDB has one), for the app's Tables page.

Settings (Settings > Secrets and variables > Actions):
  TSDB_KEY            Secret. Your TheSportsDB key. Needed: the free key can't read whole seasons.
  FOOTBALL_LEAGUES    Variable, optional. Extra TheSportsDB league ids to include, e.g. "4500,4501".
  FOOTBALL_SKIP       Variable, optional. League ids to leave out.
  OTHER_SPORTS        Variable. "on" adds the other sports (OTHER) to the files the app reads.
                      Off until you set it, so you can run --check first, and so app versions from
                      before other sports were supported don't list them as football.
  OTHER_SKIP          Variable, optional. League ids from OTHER to leave out.
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
CHECK = "--check" in sys.argv

# English leagues below League Two (ESPN covers League Two and above).
NONLEAGUE = re.compile(r"national league|southern|isthmian|northern premier", re.I)
NOT_THESE = re.compile(r"women|u21|u23|u18|youth|cup|trophy|vase|shield|reserve", re.I)

# Other sports ESPN doesn't cover, found by name in TheSportsDB's league lists. Each: the app's
# sport, where it's shown by default, how guides name it, a game's usual length (minutes), and
# which of TheSportsDB's lists to look in (country, TheSportsDB's sport name) with a name pattern.
# A league with no games on TheSportsDB is left out (the run's summary says what was found).
OTHER = [
    {"sport": "RUGBY", "regions": ["UK", "IE"], "words": ["Super League", "Rugby League"], "minutes": 110,
     "look": [("England", "Rugby")], "name": r"super league|challenge cup|championship.*rugby league|rugby league.*championship",
     "skip": r"women|wheelchair|reserve|academy|union|prem"},
    {"sport": "RUGBY", "regions": ["AU"], "words": ["NRL", "Rugby League", "State of Origin"], "minutes": 110,
     "look": [("Australia", "Rugby")], "name": r"\bnrl\b|national rugby league|state of origin",
     "skip": r"women|nrlw|reserve|cup$"},
    # (The County Championship isn't kept up on TheSportsDB: its last season there is 2023.)
    {"sport": "CRICKET", "regions": ["UK", "IE"], "words": ["T20 Blast", "Vitality Blast", "The Hundred"], "minutes": 210,
     "look": [("England", "Cricket")], "name": r"blast|the hundred",
     "skip": r"women|second xi|2nd xi"},
    {"sport": "CRICKET", "regions": ["UK", "IE", "AU", "OTHER"], "words": ["IPL", "Indian Premier League"], "minutes": 210,
     "look": [("India", "Cricket")], "name": r"indian premier league|\bipl\b", "skip": r"women"},
    {"sport": "CRICKET", "regions": ["AU"], "words": ["Big Bash", "BBL"], "minutes": 210,
     "look": [("Australia", "Cricket")], "name": r"big bash", "skip": r"women|wbbl"},
    {"sport": "CRICKET", "regions": ["UK", "IE", "AU", "OTHER"], "words": ["Test Match", "ODI", "T20 International"], "minutes": 480,
     "look": [("World", "Cricket")], "name": r"test|one day international|\bodi\b|t20 international|twenty20 international|world cup|champions trophy",
     "skip": r"women|u19|under.19|qualif"},
    {"sport": "HOCKEY", "regions": ["UK", "IE"], "words": ["Elite League", "Elite Ice Hockey"], "minutes": 150,
     "look": [("England", "Ice Hockey"), ("United Kingdom", "Ice Hockey"), ("Scotland", "Ice Hockey")], "name": r"elite", "skip": r"women"},
    # The AHL (the NHL's development league): ESPN doesn't carry it.
    {"sport": "HOCKEY", "regions": ["US", "CA"], "words": ["AHL", "American Hockey League"], "minutes": 150,
     "look": [("United States", "Ice Hockey"), ("USA", "Ice Hockey"), ("Canada", "Ice Hockey")],
     "name": r"american hockey league|\bahl\b", "skip": r"women|junior|u18|u20"},
    # Gaelic games: only the National Football League has games on TheSportsDB (the championships
    # and hurling have none).
    {"sport": "GAELIC", "regions": ["IE", "UK"], "words": ["National Football League", "Allianz League", "Allianz Football League", "GAA"], "minutes": 100,
     "look": [("Ireland", "Gaelic")], "name": r"national football league",
     "skip": r"ladies|camogie|minor|u20|junior|intermediate"},
    {"sport": "NETBALL", "regions": ["UK", "IE"], "words": ["Netball Super League", "Netball"], "minutes": 90,
     "look": [("England", "Netball"), ("United Kingdom", "Netball")], "name": r"super league|netball", "skip": r"u21|u19"},
    {"sport": "NETBALL", "regions": ["AU"], "words": ["Super Netball", "Netball"], "minutes": 90,
     "look": [("Australia", "Netball")], "name": r"super netball|netball", "skip": r"u21|u19"},
]

_last = [0.0]


def log(msg):
    print(msg, flush=True)


def get(path, v2=False, quiet404=False):
    """One request, spaced out and retried. None on failure. The key never appears in output.
    v2 with no path: the live scores; with a path: that v2 address."""
    url = ("https://www.thesportsdb.com/api/v2/json/" + path) if (v2 and path) else LIVE_URL if v2 else BASE + path
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
            if not (quiet404 and e.code == 404):
                log("  %s: HTTP %s" % ((path or "livescore") if v2 else path.split("?")[0], e.code))
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


def state_of(status, hs, as_, start, now, minutes=115):
    st = (status or "").strip().lower()
    if st in OFF:
        return "off"
    if st in FINISHED:
        return "post"
    if st in LIVE or re.match(r"^\d{1,3}('|\+)", st):
        return "in"
    if hs is not None and as_ is not None and start is not None:
        return "post" if now - start > dt.timedelta(minutes=minutes + 20) else "in"
    return "pre"


def norm_event(e, now, minutes=115):
    home, away = (e.get("strHomeTeam") or "").strip(), (e.get("strAwayTeam") or "").strip()
    if not home or not away:
        return None
    start, has_time = start_of(e)
    if start is None:
        return None
    hs, as_ = to_int(e.get("intHomeScore")), to_int(e.get("intAwayScore"))
    status = (e.get("strStatus") or "").strip()
    state = state_of(status, hs, as_, start, now, minutes)
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

def read_table(lid, season, use_logos):
    """The league table as the app reads it, or [] (cups, leagues TheSportsDB has no table for)."""
    rows = (get("lookuptable.php?l=%s&s=%s" % (lid, urllib.parse.quote(season)), quiet404=True) or {}).get("table") or []
    out = []
    for r in rows:
        tid = str(r.get("idTeam") or "").strip()
        name = clean_name(r.get("strTeam") or "")
        if not tid or not name:
            continue
        row = {"pos": to_int(r.get("intRank")) or len(out) + 1, "id": tid, "name": name,
               "p": to_int(r.get("intPlayed")), "w": to_int(r.get("intWin")), "d": to_int(r.get("intDraw")),
               "l": to_int(r.get("intLoss")), "gd": to_int(r.get("intGoalDifference")), "pts": to_int(r.get("intPoints"))}
        form = re.sub(r"[^WDLwdl]", "", r.get("strForm") or "").upper()
        if form:
            row["form"] = form[-5:]
        note = (r.get("strDescription") or "").strip()
        if note:
            row["note"] = note
        badge = (r.get("strBadge") or "").strip()
        if use_logos and badge.startswith("https://"):
            row["badge"] = badge
        out.append({k: v for k, v in row.items() if v is not None})
    return sorted(out, key=lambda x: x["pos"])


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


def season_after(season):
    """"2025-2026" -> "2026-2027"; "2026" -> "2027"; None if it isn't a season like that."""
    m = re.match(r"^(\d{4})(?:-(\d{4}))?$", season or "")
    if not m:
        return None
    a = int(m.group(1)) + 1
    return "%d-%d" % (a, int(m.group(2)) + 1) if m.group(2) else str(a)


def season_before(season):
    """"2026" -> "2025"; "2025-2026" -> "2024-2025"; None if it isn't a season like that."""
    m = re.match(r"^(\d{4})(?:-(\d{4}))?$", season or "")
    if not m:
        return None
    a = int(m.group(1)) - 1
    return "%d-%d" % (a, int(m.group(2)) - 1) if m.group(2) else str(a)


def last_season_note(lid, season, now, minutes):
    """Check only, for a league with nothing coming up: how its last season looked."""
    prev = season_before(season)
    if not prev:
        return "-"
    rows = (get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(prev))) or {}).get("events") or []
    evs = [ev for ev in (norm_event(e, now, minutes) for e in rows) if ev]
    if not evs:
        return "%s: no games" % prev
    done = [e for e in evs if e["state"] == "post"]
    scored = sum(1 for e in done if "hs" in e)
    timed = sum(1 for e in evs if e.get("hasTime"))
    return "%s: %d games, %d of %d scored, %d timed" % (prev, len(evs), scored, len(done), timed)


def find_other(summary):
    """OTHER's leagues on TheSportsDB: league id -> (name, the OTHER entry)."""
    chosen = {}
    skip_ids = set(env_ids("OTHER_SKIP"))
    seen_lists = {}
    for spec in OTHER:
        for country, sport in spec["look"]:
            key = (country, sport)
            if key not in seen_lists:
                rows = get("search_all_leagues.php?c=%s&s=%s" % (urllib.parse.quote(country), urllib.parse.quote(sport))) or {}
                seen_lists[key] = rows.get("countries") or rows.get("leagues") or []
            for r in seen_lists[key]:
                lid, name = str(r.get("idLeague") or ""), (r.get("strLeague") or "")
                if not lid or lid in chosen or lid in skip_ids:
                    continue
                if re.search(spec["name"], name, re.I) and not re.search(spec["skip"], name, re.I):
                    chosen[lid] = (name, spec)
    found = ["%s / %s: %s" % (c, sp, ", ".join("%s (%s)" % (r.get("strLeague"), r.get("idLeague")) for r in rows) or "nothing listed")
             for (c, sp), rows in seen_lists.items()]
    summary += ["", "<details><summary>Other sports: what TheSportsDB lists</summary>", ""] + \
               ["- " + f for f in found] + ["", "</details>"]
    return chosen


def full_run():
    summary = ["## " + ("Check: TheSportsDB data (nothing written)" if CHECK else "Non-league football and other sports (full)"), ""]
    if FREE:
        summary.append("No TSDB_KEY secret: the free key can't read whole seasons, so nothing was done.")
        log(summary[-1])
        return summary
    now = dt.datetime.utcnow()
    today = now.date()
    keep_from = (now - dt.timedelta(days=KEEP_DAYS_BACK)).strftime("%Y-%m-%d")
    logos = {s.lower() for s in env_ids("FOOTBALL_LOGOS")}
    details = []
    table = []
    leagues = {lid: (name, None) for lid, name in find_leagues(details).items()}
    with_other = CHECK or (os.environ.get("OTHER_SPORTS") or "").strip().lower() in ("on", "yes", "true", "1")
    for lid, v in (find_other(details) if with_other else {}).items():
        leagues.setdefault(lid, v)
    log("Leagues: %s" % ", ".join("%s %s" % (k, v[0]) for k, v in leagues.items()))
    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for lid, (name, spec) in leagues.items():
        minutes = (spec or {}).get("minutes", 115)
        info = ((get("lookupleague.php?id=%s" % lid) or {}).get("leagues") or [{}])[0] or {}
        name = info.get("strLeague") or name or lid
        season = (info.get("strCurrentSeason") or "").strip() or season_now(today)
        log("Reading %s (%s), season %s..." % (name, lid, season))
        rows = (get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(season))) or {}).get("events") or []
        # TheSportsDB's "current season" isn't always moved on (several divisions still said
        # 2025-2026 in October 2026): nothing there, try the next season.
        nxt_season = season_after(season)
        if not rows and nxt_season and nxt_season[:4] <= str(today.year):
            rows = (get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(nxt_season))) or {}).get("events") or []
            if rows:
                season = nxt_season
        if not rows:
            rows = ((get("eventspastleague.php?id=%s" % lid) or {}).get("events") or []) + \
                   ((get("eventsnextleague.php?id=%s" % lid) or {}).get("events") or [])
        events = {}
        for e in rows:
            ev = norm_event(e, now, minutes)
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
            # v2's team list (v1's lookup_all_teams answers 404 with this key), then v1's search.
            data = get("list/teams/%s" % lid, v2=True, quiet404=True) or {}
            rows = data.get("list") or data.get("teams") or []
            if not rows:
                rows = (get("search_all_teams.php?l=%s" % urllib.parse.quote(info.get("strLeague") or name), quiet404=True) or {}).get("teams") or []
            for t in rows:
                b = (t.get("strBadge") or t.get("strTeamBadge") or "").strip()
                if b.startswith("https://") and t.get("idTeam"):
                    badges[str(t["idTeam"])] = b
        team_list = [dict({"id": tid, "name": tn}, **({"badge": badges[tid]} if tid in badges else {}))
                     for tid, tn in sorted(teams.items(), key=lambda kv: kv[1].lower())]
        league_badge = (info.get("strBadge") or "").strip() if use_logos else ""
        upcoming = sum(1 for e in events if e["state"] == "pre")
        done = [e for e in events if e["state"] == "post"]
        scored = sum(1 for e in done if "hs" in e)
        sport = (spec or {}).get("sport", "FOOTBALL")
        last = max((e["start"][:10] for e in done), default="-")
        nxt = min((e["start"][:10] for e in events if e["state"] == "pre"), default="-")
        timed = sum(1 for e in events if e.get("hasTime"))
        # Good: games coming up, kick-off times, and scores on the results.
        if not events:
            verdict = "no games: left out"
        elif done and scored * 10 < len(done) * 8:
            verdict = "thin: scores missing"
        elif events and timed * 10 < len(events) * 8:
            verdict = "thin: no kick-off times"
        elif not upcoming:
            verdict = "nothing coming up (off season?)"
        else:
            verdict = "good"
        # The table (one request): for the app's Tables page.
        table_rows = read_table(lid, season, use_logos) if events else []
        # Off season: did last season have proper data? (Check only: one more request.)
        before = last_season_note(lid, season, now, minutes) if CHECK and not upcoming else ""
        row = "| %s | %s | %s | %s | %d | %d | %d | %s | %s | %s | %s | %s | %s |" % (
            clean_name(name), sport.title(), lid, season, len(events), upcoming, len(teams),
            ("%d of %d" % (scored, len(done))) if done else "-", last, nxt,
            ("%d teams" % len(table_rows)) if table_rows else "-", verdict, before or "-")
        table.append(row)
        # No games on TheSportsDB for this one: left out of the app (it would be an empty league).
        if not events or CHECK:
            continue
        data = {"league": lid, "season": season, "events": events}
        if table_rows:
            data["table"] = table_rows
        write_if_changed(os.path.join(OUT_DIR, "%s.json" % lid), data)
        entry = {
            "id": lid, "name": clean_name(name), "short": short_name(name), "season": season,
            "badge": league_badge or None, "teams": team_list, "games": len(events), "upcoming": upcoming,
        }
        if spec:
            entry.update({"sport": spec["sport"], "regions": spec["regions"], "words": spec["words"], "minutes": spec["minutes"]})
        index.append(entry)
    summary += ["| League | Sport | Id | Season | Games | Upcoming | Teams | Scores in results | Last result | Next game | Table | Verdict | Last season |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"] + table
    summary += ["", "Leagues with no games on TheSportsDB are left out of the app."] + details
    if CHECK:
        summary += ["", "Check only: nothing was written. A thin league can be left out with the OTHER_SKIP (or FOOTBALL_SKIP) variable."]
    elif index:
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
    length = {lg["id"]: lg.get("minutes", 115) for lg in index.get("leagues") or []}
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
            if ev.get("state") == "in" or (ev.get("state") == "pre" and start - dt.timedelta(minutes=20) <= now <= start + dt.timedelta(minutes=length[lg["id"]] + 60)):
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
                ev = norm_event(e, now, length.get(lid, 115))
                if ev:
                    updates[ev["id"]] = ev
    live = get("", v2=True) or {}
    live_rows = live.get("livescore") or live.get("events") or []
    n_live = 0
    for e in live_rows:
        if str(e.get("idLeague") or "") not in files:
            continue
        ev = norm_event(e, now, length.get(str(e.get("idLeague")), 115))
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
