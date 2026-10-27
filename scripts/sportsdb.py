#!/usr/bin/env python3
"""
Every sport the Nuvio + IPTV Sports page gets from TheSportsDB, from one list: leagues.txt.
Add a line there to add a league; nothing else needs changing. The app only ever reads the files
this writes, so the TheSportsDB key stays in this repo's secrets.

Three modes:
  python scripts/sportsdb.py           Full: every league's season (games or events, teams,
                                       table). Run once a day.
  python scripts/sportsdb.py --scores  Scores: today's games, for leagues with a game on now.
                                       Run every 15 minutes.
  python scripts/sportsdb.py --check   Reads everything a full run would, reports, writes nothing.

Files (written only when something changed):
  sportsdb/index.json        Every league: name, sport, where it's shown, how guides name it,
                             teams (team sports), and which of the app's leagues it fills (app=).
  sportsdb/<league id>.json  Its games (team sports) or events (racing, fighting...), from a few
                             weeks back to the end of the season, and its table when there is one.

Settings: only the TSDB_KEY secret (your paid TheSportsDB key).

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
V2 = "https://www.thesportsdb.com/api/v2/json/"
LIST_FILE = "leagues.txt"
OUT_DIR = "sportsdb"
CHECK = "--check" in sys.argv
GAP = [0.7 if not FREE else 3.5]
BUDGET_SECONDS = 15 * 60
STARTED = time.time()
EVERYWHERE = ["US", "UK", "IE", "CA", "AU", "OTHER"]
TEAM_DAYS_BACK = 45
EVENT_DAYS_BACK = 4
DAYS_AHEAD_MAX = 200

# TheSportsDB's sport -> the app's sport, and a game's or session's usual length.
SPORTS = {
    "soccer": ("FOOTBALL", 115), "motorsport": ("RACING", 150), "fighting": ("FIGHTING", 240),
    "rugby": ("RUGBY", 110), "cricket": ("CRICKET", 420), "ice hockey": ("HOCKEY", 150),
    "netball": ("NETBALL", 90), "gaelic": ("GAELIC", 100), "darts": ("DARTS", 300),
    "snooker": ("SNOOKER", 300), "golf": ("GOLF", 360), "tennis": ("TENNIS", 600),
    "basketball": ("BASKETBALL", 150), "american football": ("AMERICAN_FOOTBALL", 200),
    "baseball": ("BASEBALL", 180), "australian football": ("AUSSIE_RULES", 150),
    "volleyball": ("VOLLEYBALL", 120), "cycling": ("OTHER", 300), "lacrosse": ("LACROSSE", 120),
}
APP_SPORTS = {v[0] for v in SPORTS.values()} | {"WRESTLING", "OTHER"}
# Lists searched when a league is given by name and TheSportsDB's search doesn't find it.
SEARCH_SPORTS = ["Motorsport", "Fighting", "Rugby", "Cricket", "Ice Hockey", "Netball", "Darts", "Snooker",
                 "Golf", "Tennis", "Cycling", "Basketball", "American Football", "Baseball", "Australian Football", "Soccer"]

_last = [0.0]


def log(msg):
    print(msg, flush=True)


def time_left():
    return BUDGET_SECONDS - (time.time() - STARTED)


def get(path, v2=False, quiet404=False):
    """One request, spaced out and retried. None on failure. The key never appears in output."""
    url = (V2 + path) if v2 else BASE + path
    headers = {"User-Agent": "nuvio-data/2.0 (GitHub Actions)"}
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
                log("  %s: HTTP %s" % (path.split("?")[0], e.code))
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log("  %s: %s" % (path.split("?")[0], type(e).__name__))
            time.sleep(5)
    return None


def rows_of(data, *keys):
    for k in keys:
        v = (data or {}).get(k)
        if v:
            return v
    return []


# ------------------------------------------------------------------ leagues.txt

def split_list(s):
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def parse_list(path):
    """leagues.txt -> [{"line", "id" or "name" or "group", options...}]."""
    out = []
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            head, opts = parts[0], parts[1:]
            item = {"line": n, "text": line}
            m = re.match(r"^([^/:]+)/([^:]+):(.+)$", head)
            if m:
                item["group"] = {"countries": split_list(m.group(1)), "sport": m.group(2).strip(), "words": split_list(m.group(3))}
            elif head.isdigit():
                item["id"] = head
            else:
                item["name"] = head
            for o in opts:
                if "=" in o:
                    k, v = o.split("=", 1)
                    item[k.strip().lower()] = v.strip()
                elif o:
                    item[o.strip().lower()] = True
            out.append(item)
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


_league_lists = {}


def league_list(sport=None, country=None):
    key = (sport, country)
    if key not in _league_lists:
        if sport is None and country is None:
            data = get("all_leagues.php") or {}
        else:
            q = []
            if country:
                q.append("c=%s" % urllib.parse.quote(country))
            if sport:
                q.append("s=%s" % urllib.parse.quote(sport))
            data = get("search_all_leagues.php?%s" % "&".join(q)) or {}
        _league_lists[key] = rows_of(data, "countries", "leagues")
    return _league_lists[key]


def names_of(row):
    return [row.get("strLeague") or ""] + split_list(row.get("strLeagueAlternate"))


def find_by_name(name):
    """(id, row, note). Exact name first, then every word of it in one league's name."""
    want = norm(name)
    pools = [league_list()]
    data = get("search/league/%s" % urllib.parse.quote(name), v2=True, quiet404=True)
    if data:
        pools.insert(0, rows_of(data, "search", "leagues"))
    for p in pools:
        for r in p:
            if any(norm(n) == want for n in names_of(r)):
                return str(r.get("idLeague")), r, None
    words = want.split()
    candidates = {}
    for sport in SEARCH_SPORTS:
        if time_left() < 60:
            break
        for r in league_list(sport):
            if any(norm(n) == want for n in names_of(r)):
                return str(r.get("idLeague")), r, None
            if all(w in norm(" ".join(names_of(r))).split() for w in words):
                candidates[str(r.get("idLeague"))] = r
        if candidates:
            break
    if len(candidates) == 1:
        lid, r = next(iter(candidates.items()))
        return lid, r, None
    if candidates:
        # The closest: the fewest other words ("FIA", "Championship" and the like don't count).
        filler = {"fia", "fim", "championship", "championships", "world", "series", "the", "of", "cup"}

        def extra(kv):
            nm = norm(kv[1].get("strLeague")).split()
            return (sum(1 for w in nm if w not in words and w not in filler), len(nm))
        lid, r = min(candidates.items(), key=extra)
        others = ", ".join("%s (%s)" % (v.get("strLeague"), k) for k, v in list(candidates.items())[:6] if k != lid)
        return lid, r, "picked the closest; others: %s" % others
    return None, None, "not found on TheSportsDB"


def resolve(items, summary):
    """Every line -> [(league id, item)] (a group line can give several)."""
    out = []
    seen = set()
    notes = []
    for it in items:
        found = []
        if "id" in it:
            found = [(it["id"], None)]
            notes.append("- line %d **%s**: by id" % (it["line"], it["id"]))
        elif "name" in it:
            lid, row, note = find_by_name(it["name"])
            if lid:
                found = [(lid, row)]
            notes.append("- line %d **%s**: %s" % (it["line"], it["name"], (
                "%s (%s)%s" % ((row or {}).get("strLeague") or it["name"], lid, ("; " + note) if note else "")) if lid else note))
        else:
            g = it["group"]
            skip = [norm(s) for s in split_list(it.get("skip"))]
            words = [norm(w) for w in g["words"]]
            for country in g["countries"]:
                for r in league_list(g["sport"], country):
                    nm = norm(r.get("strLeague"))
                    if any(w and (" " + w + " ") in (" " + nm + " ") or (len(w) > 4 and w in nm) for w in words) and \
                            not any(s and s in nm for s in skip):
                        found.append((str(r.get("idLeague")), r))
            notes.append("- line %d **%s**: %s" % (it["line"], it["text"].split("|")[0].strip(), ", ".join(
                "%s (%s)" % (r.get("strLeague"), lid) for lid, r in found) or "nothing matched"))
        for lid, row in found:
            if lid and lid not in seen:
                seen.add(lid)
                out.append((lid, it))
    summary += ["", "<details><summary>What each line of leagues.txt found</summary>", ""] + notes + ["", "</details>"]
    return out


# ------------------------------------------------------------------ games and events

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
        s, has_time = stamp.replace(" ", "T")[:19], True
    elif date and tm and tm[:5] != "00:00":
        s, has_time = "%sT%s" % (date, tm[:8]), True
    elif date:
        s, has_time = "%sT00:00:00" % date, False
    else:
        return None, False
    if len(s) == 16:
        s += ":00"
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S"), has_time
    except ValueError:
        return None, False


def state_of(status, hs, as_, start, now, minutes):
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


def about(text):
    t = " ".join((text or "").split())
    if len(t) < 20:
        return None
    if len(t) <= 400:
        return t
    cut = t[:400]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > 120 else cut.rstrip() + "…"


def team_event(e, now, minutes):
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
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "hasTime": has_time, "state": state,
    }
    if state in ("in", "post") and hs is not None and as_ is not None:
        out["hs"], out["as"] = hs, as_
    progress = (e.get("strProgress") or "").strip()
    if state == "in":
        out["status"] = (progress + "'") if progress.isdigit() else (status.upper() if status else "LIVE")
    elif state == "off":
        out["status"] = "Postponed" if status.lower().startswith("p") else (status or "Off")
    rnd = to_int(e.get("intRound"))
    if rnd:
        out["round"] = rnd
    venue = (e.get("strVenue") or "").strip()
    if venue:
        out["venue"] = venue
    return out if out["id"] else None


def named_event(e, now, minutes):
    """A race session, a fight card, a wrestling show: a name, not two teams."""
    if (e.get("strStatus") or "").strip().lower() in OFF:
        return None
    name = (e.get("strEvent") or "").strip()
    start, has_time = start_of(e)
    if not name or start is None:
        return None
    out = {"id": str(e.get("idEvent") or "%s:%s" % (name, start.isoformat())), "name": name,
           "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "hasTime": has_time}
    for k, f in (("venue", "strVenue"), ("city", "strCity"), ("country", "strCountry")):
        v = (e.get(f) or "").strip()
        if v:
            out[k] = v
    a = about(e.get("strDescriptionEN"))
    if a:
        out["about"] = a
    rnd = to_int(e.get("intRound"))
    if rnd:
        out["round"] = rnd
    return out


def season_events(lid, info, today):
    """The current season's events (with TheSportsDB's season names tried in every form)."""
    season = (info.get("strCurrentSeason") or "").strip()
    tried = []
    y = today.year
    for s in [season, str(y), "%d-%d" % (y, y + 1), "%d-%d" % (y - 1, y), str(y + 1)]:
        if not s or s in tried:
            continue
        tried.append(s)
        rows = rows_of(get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(s))), "events")
        if rows:
            # A season that's over: the next one too, when it's already listed.
            more = []
            m = re.match(r"^(\d{4})(?:-(\d{4}))?$", s)
            if m and max((r.get("dateEvent") or "") for r in rows) < today.isoformat():
                a = int(m.group(1)) + 1
                nxt = "%d-%d" % (a, int(m.group(2)) + 1) if m.group(2) else str(a)
                more = rows_of(get("eventsseason.php?id=%s&s=%s" % (lid, urllib.parse.quote(nxt))), "events")
                if more:
                    s = nxt
            return rows + more, s
    rows = rows_of(get("eventspastleague.php?id=%s" % lid), "events") + rows_of(get("eventsnextleague.php?id=%s" % lid), "events")
    return rows, season or str(y)


def read_table(lid, season, use_logos):
    rows = rows_of(get("lookuptable.php?l=%s&s=%s" % (lid, urllib.parse.quote(season)), quiet404=True), "table")
    out = []
    for r in rows:
        tid = str(r.get("idTeam") or "").strip()
        name = (r.get("strTeam") or "").strip()
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


def team_rows(lid, league_name):
    data = get("list/teams/%s" % lid, v2=True, quiet404=True) or {}
    rows = rows_of(data, "list", "teams")
    if not rows:
        rows = rows_of(get("search_all_teams.php?l=%s" % urllib.parse.quote(league_name), quiet404=True), "teams")
    return rows


BRAND_DROP = {"mens", "men", "womens", "women", "wrestling", "tag", "team", "division", "brand", "the"}


def brands_of(lid, info):
    """Wrestling: a promotion's shows (NXT, Raw...) and their logos, from its teams."""
    league_words = {w.lower() for w in (info.get("strLeague") or "").split()}
    best = {}
    for t in team_rows(lid, info.get("strLeague") or ""):
        badge = (t.get("strBadge") or t.get("strTeamBadge") or "").strip()
        name = (t.get("strTeam") or "").strip()
        if not badge.startswith("https://") or not name:
            continue
        words = [w for w in name.lower().replace("'", "").split() if w not in BRAND_DROP and w not in league_words]
        if not words:
            continue
        womens = "women" in name.lower()
        if words[0] not in best or (best[words[0]][0] and not womens):
            best[words[0]] = (womens, {"word": words[0], "name": name, "badge": badge})
    return [v[1] for _, v in sorted(best.items())]


def short_name(name):
    n = re.sub(r"^English\s+", "", name or "", flags=re.I)
    if re.search(r"national league", n, re.I):
        rest = re.sub(r"national league", "", n, flags=re.I).strip()
        return ("NL " + rest[:1].upper()).strip() if rest else "NL"
    words = [w for w in re.split(r"[\s\-]+", n) if w and w.lower() not in ("league", "division", "football", "the", "of", "championship", "fia", "world")]
    if len(words) == 1:
        return words[0][:7].upper()
    return "".join(w[0].upper() for w in words)[:5] or n[:5].upper()


def clean_name(name):
    return re.sub(r"^English\s+", "", (name or "").strip(), flags=re.I)


def app_sport(item, info):
    s = (item.get("sport") or "").strip().upper().replace(" ", "_")
    if s in APP_SPORTS:
        return s
    app = item.get("app") or ""
    if app in ("guide/wwe", "guide/aew", "guide/wrestling") or "wrestl" in (info.get("strLeague") or "").lower():
        return "WRESTLING"
    if app == "guide/boxing":
        return "FIGHTING"
    if app == "guide/motogp":
        return "RACING"
    return SPORTS.get((info.get("strSport") or "").strip().lower(), ("OTHER", 150))[0]


def full_run():
    summary = ["## " + ("Check: TheSportsDB data (nothing written)" if CHECK else "Sports from TheSportsDB (full)"), ""]
    if FREE:
        summary.append("No TSDB_KEY secret: the free key can't read whole seasons, so nothing was done.")
        return summary
    if not os.path.exists(LIST_FILE):
        summary.append("No leagues.txt: upload nuvio-data.zip first.")
        return summary
    now = dt.datetime.utcnow()
    today = now.date()
    leagues = resolve(parse_list(LIST_FILE), summary)
    log("Leagues: %s" % ", ".join(lid for lid, _ in leagues))
    os.makedirs(OUT_DIR, exist_ok=True)
    index, table = [], []
    for lid, item in leagues:
        if time_left() < 90:
            table.append("| %s | | | | | | out of time: kept from last run |" % lid)
            old = old_index_entry(lid)
            if old:
                index.append(old)
            continue
        info = (rows_of(get("lookupleague.php?id=%s" % lid), "leagues") or [{}])[0] or {}
        name = clean_name(info.get("strLeague") or item.get("name") or lid)
        sport = app_sport(item, info)
        minutes = to_int(item.get("minutes")) or SPORTS.get((info.get("strSport") or "").strip().lower(), ("", 150))[1]
        log("Reading %s (%s)..." % (name, lid))
        rows, season = season_events(lid, info, today)
        teams_kind = sum(1 for e in rows if e.get("strHomeTeam") and e.get("strAwayTeam")) * 2 > len(rows) if rows else False
        keep_from = (now - dt.timedelta(days=TEAM_DAYS_BACK if teams_kind else EVENT_DAYS_BACK)).strftime("%Y-%m-%d")
        keep_to = (now + dt.timedelta(days=DAYS_AHEAD_MAX)).strftime("%Y-%m-%d")
        events = {}
        for e in rows:
            ev = team_event(e, now, minutes) if teams_kind else named_event(e, now, minutes)
            if ev and keep_from <= ev["start"][:10] <= keep_to:
                events[ev["id"]] = ev
        events = sorted(events.values(), key=lambda x: (x["start"], x.get("home") or x.get("name")))
        if not teams_kind:
            # The same show listed twice a day apart (TheSportsDB does this): once.
            seen, unique = {}, []
            for ev in events:
                k = norm(ev["name"])
                when = dt.datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%SZ")
                if k in seen and when - seen[k][0] <= dt.timedelta(days=2):
                    first = seen[k][1]
                    if ev["hasTime"] and not first["hasTime"]:
                        # Keep the copy with a time on it.
                        both = dict(first, **ev)
                        unique[unique.index(first)] = both
                        seen[k] = (when, both)
                    continue
                seen[k] = (when, ev)
                unique.append(ev)
            events = unique
        use_logos = bool(item.get("logos"))
        teams = {}
        badges = {}
        if teams_kind:
            for ev in events:
                teams[ev["homeId"]] = ev["home"]
                teams[ev["awayId"]] = ev["away"]
            if use_logos:
                for t in team_rows(lid, info.get("strLeague") or name):
                    b = (t.get("strBadge") or t.get("strTeamBadge") or "").strip()
                    if b.startswith("https://") and t.get("idTeam"):
                        badges[str(t["idTeam"])] = b
        upcoming = sum(1 for e in events if e.get("state", "pre") == "pre" and (
            e["start"] >= now.strftime("%Y-%m-%dT%H:%M:%SZ") if e["hasTime"] else e["start"][:10] >= today.isoformat()))
        table_rows = read_table(lid, season, use_logos) if teams_kind and events else []
        verdict = "good" if upcoming else ("no events: left out" if not events else "nothing coming up (off season?)")
        table.append("| %s | %s | %s | %s | %s | %d | %d | %s |" % (
            name, sport.title().replace("_", " "), lid, "games" if teams_kind else "events", season, len(events), upcoming, verdict))
        if not events or CHECK:
            continue
        data = {"league": lid, "season": season, "events": events}
        if table_rows:
            data["table"] = table_rows
        write_if_changed(os.path.join(OUT_DIR, "%s.json" % lid), data)
        regions = item.get("regions")
        regions = EVERYWHERE if (regions or "").strip().lower() == "everywhere" else split_list(regions)
        words = [w for w in [name] + split_list(info.get("strLeagueAlternate")) + split_list(item.get("words")) if w]
        entry = {
            "id": lid, "name": name, "short": short_name(name), "season": season,
            "sport": sport, "kind": "teams" if teams_kind else "event", "regions": regions,
            "words": list(dict.fromkeys(words)), "minutes": minutes,
            "tsdbSport": (info.get("strSport") or "").strip(),
            "games": len(events), "upcoming": upcoming,
        }
        badge = (info.get("strBadge") or "").strip()
        if use_logos and badge.startswith("https://"):
            entry["badge"] = badge
        if item.get("app"):
            entry["app"] = item["app"]
        if item.get("brands") and use_logos:
            entry["brands"] = brands_of(lid, info)
        if teams_kind:
            entry["teams"] = [dict({"id": tid, "name": tn}, **({"badge": badges[tid]} if tid in badges else {}))
                              for tid, tn in sorted(teams.items(), key=lambda kv: kv[1].lower())]
        index.append(entry)
    summary += ["| League | Sport | Id | Kind | Season | Kept | Coming up | Verdict |", "|---|---|---|---|---|---|---|---|"] + table
    if CHECK:
        summary += ["", "Check only: nothing was written."]
    elif index:
        write_if_changed(os.path.join(OUT_DIR, "index.json"), {"source": "TheSportsDB (thesportsdb.com)", "format": 2, "leagues": index})
        # Files of leagues no longer in the list go.
        keep = {"index.json"} | {"%s.json" % e["id"] for e in index}
        for f in os.listdir(OUT_DIR):
            if f.endswith(".json") and f not in keep:
                os.remove(os.path.join(OUT_DIR, f))
    else:
        summary += ["", "No leagues found, so nothing was changed."]
    return summary


def old_index_entry(lid):
    try:
        with open(os.path.join(OUT_DIR, "index.json"), encoding="utf-8") as f:
            for e in json.load(f).get("leagues") or []:
                if e.get("id") == lid:
                    return e
    except (OSError, ValueError):
        pass
    return None


# ------------------------------------------------------------------ scores run

def scores_run():
    summary = ["## Sports scores", ""]
    if FREE:
        summary.append("No TSDB_KEY secret: skipped.")
        return summary
    path = os.path.join(OUT_DIR, "index.json")
    if not os.path.exists(path):
        summary.append("No sportsdb/index.json yet: run the full update first.")
        return summary
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    now = dt.datetime.utcnow()
    files, busy, length, sport_of = {}, [], {}, {}
    for lg in index.get("leagues") or []:
        if lg.get("kind") != "teams":
            continue
        p = os.path.join(OUT_DIR, "%s.json" % lg["id"])
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        files[lg["id"]] = (p, data)
        length[lg["id"]] = lg.get("minutes", 115)
        sport_of[lg["id"]] = (lg.get("tsdbSport") or "soccer").lower().replace(" ", "_")
        for ev in data.get("events") or []:
            try:
                start = dt.datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%SZ")
            except (KeyError, ValueError):
                continue
            if ev.get("state") == "in" or (ev.get("state") == "pre" and
                                          start - dt.timedelta(minutes=20) <= now <= start + dt.timedelta(minutes=length[lg["id"]] + 60)):
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
            for e in rows_of(get("eventsday.php?d=%s&l=%s" % (d, lid)), "events"):
                ev = team_event(e, now, length.get(lid, 115))
                if ev:
                    updates[ev["id"]] = ev
    n_live = 0
    for sport in sorted({sport_of[l] for l in busy}):
        live = get("livescore/%s" % sport, v2=True, quiet404=True) or {}
        for e in rows_of(live, "livescore", "events"):
            lid = str(e.get("idLeague") or "")
            if lid not in files:
                continue
            ev = team_event(e, now, length.get(lid, 115))
            if not ev:
                continue
            if ev["state"] == "pre":
                ev["state"], ev["status"] = "in", "LIVE"
            n_live += 1
            updates[ev["id"]] = dict(updates.get(ev["id"], {}), **ev)
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
    summary.append("Checked %d league(s); live feeds had %d of our games; %d game(s) changed." % (len(busy), n_live, changed))
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
