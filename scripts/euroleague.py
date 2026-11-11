#!/usr/bin/env python3
"""EuroLeague live scores from the league's own public feed, into sportsdb/4546.json.

TheSportsDB's live feed doesn't cover EuroLeague, so its games stayed "upcoming" after they
started. This asks the official feed (api-live.euroleague.net / live.euroleague.net) for games
that are about to start, on, or just finished, and updates the same fields the app already
reads (state, status, hs, as) in the same file. Nothing else in the file is touched.

Safe by design: it asks nothing when no game is near, any failure leaves the file as it was,
and a game it can't match is left alone. It never raises: the ESPN job that runs it must go on.
"""
import datetime as dt
import json
import os
import re
import sys
import unicodedata
import urllib.request

LEAGUE_FILE = os.path.join(os.path.dirname(__file__), "..", "sportsdb", "4546.json")
API = "https://api-live.euroleague.net"
LIVE = "https://live.euroleague.net"

# Words that only one EuroLeague club's official name has (accents removed, lower case).
CLUBS = {
    "136066": ("anadolu", "efes"), "135088": ("baskonia",), "135424": ("bayern",),
    "136113": ("zalgiris",), "135885": ("besiktas",), "148701": ("dubai",),
    "135082": ("barcelona", "barca"), "136071": ("fenerbahce",), "136059": ("hapoel",),
    "136096": ("crvena", "zvezda", "red star"), "136102": ("partizan",),
    "135243": ("asvel", "villeurbanne", "lyon"), "136065": ("maccabi",),
    "135383": ("olimpia", "milano", "armani"), "135635": ("olympiacos",),
    "135636": ("panathinaikos",), "141489": ("paris",), "135092": ("real madrid",),
    "135097": ("valencia",), "135386": ("virtus", "bologna"),
}


def log(msg):
    print("[euroleague] " + msg, flush=True)


def plain(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def club_of(name):
    p = plain(name)
    for cid, words in CLUBS.items():
        if any(w in p for w in words):
            return cid
    return None


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "nuvio-data"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def season_code(now):
    return "E%d" % (now.year if now.month >= 7 else now.year - 1)


def walk(o):
    """Every dict anywhere inside a decoded JSON value."""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def lower_keys(d):
    return {str(k).lower(): v for k, v in d.items()}


def name_of(v):
    if isinstance(v, dict):
        v = lower_keys(v)
        return v.get("name") or v.get("clubname") or v.get("teamname") or v.get("code")
    return v


def score_of(v):
    if isinstance(v, dict):
        v = lower_keys(v).get("score")
    return to_int(v)


def schedule_games(season):
    """Games from the schedule feeds: [{home, away, hs, as, played, code}]. Tries both versions."""
    out = []
    for url in ("%s/v2/competitions/E/seasons/%s/games" % (API, season),
                "%s/v1/schedules?seasonCode=%s" % (API, season)):
        try:
            data = json.loads(get(url))
        except Exception as e:  # not JSON, blocked, or down: try the next one
            log("schedule %s: %s" % (url.split("/api")[-1][:60], e))
            continue
        n = 0
        for d in walk(data):
            k = lower_keys(d)
            home = name_of(k.get("home") or k.get("hometeam") or k.get("local"))
            away = name_of(k.get("away") or k.get("awayteam") or k.get("road"))
            if not home or not away or isinstance(home, (dict, list)) or isinstance(away, (dict, list)):
                continue
            hs = score_of(k.get("home")) if isinstance(k.get("home"), dict) else to_int(k.get("homescore"))
            a_s = score_of(k.get("away")) if isinstance(k.get("away"), dict) else to_int(k.get("awayscore"))
            status = str(k.get("status") or "").lower()
            played = k.get("played")
            if isinstance(played, str):
                played = played.strip().lower() == "true"
            if played is None:
                played = status in ("result", "played", "finished", "final", "ft")
            code = to_int(k.get("gamecode") or k.get("gamenumber") or k.get("code") or k.get("game"))
            out.append({"home": home, "away": away, "hs": hs, "as": a_s, "played": bool(played),
                        "code": code, "date": str(k.get("date") or k.get("utcdate") or "")})
            n += 1
        log("schedule: %d games from %s" % (n, url.split("euroleague.net")[-1][:50]))
        if n:
            break
    return out


def live_score(season, code):
    """(home points, away points, quarter) from the live play-by-play for one game, or None."""
    try:
        data = json.loads(get("%s/api/PlayByPlay?gamecode=%d&seasoncode=%s" % (LIVE, code, season)))
    except Exception as e:
        log("play-by-play %s: %s" % (code, e))
        return None
    last, quarter = None, 0
    keys = (("FirstQuarter", 1), ("SecondQuarter", 2), ("ThirdQuarter", 3), ("ForthQuarter", 4),
            ("FourthQuarter", 4), ("ExtraTime", 5))
    for key, q in keys:
        for p in (data.get(key) if isinstance(data, dict) else None) or []:
            a, b = to_int(p.get("POINTS_A")), to_int(p.get("POINTS_B"))
            if a is not None and b is not None:
                last, quarter = (a, b), max(quarter, q)
    if not last:
        return None
    return last[0], last[1], quarter


def main():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    try:
        with open(LEAGUE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log("no league file: %s" % e)
        return 0
    length = 135

    def parse(ev):
        try:
            return dt.datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%SZ")
        except (KeyError, ValueError):
            return None

    near = []
    for ev in data.get("events") or []:
        st = parse(ev)
        if st is None or not ev.get("hasTime", True):
            continue
        if ev.get("state") == "in" or (st - dt.timedelta(minutes=25) <= now <= st + dt.timedelta(minutes=length + 90)
                                       and ev.get("state") != "off"):
            near.append((ev, st))
    if not near:
        log("No EuroLeague game on or near now.")
        return 0

    season = season_code(now)
    games = schedule_games(season)
    if not games:
        log("Official feed gave no games; nothing changed.")
        return 0
    by_pair = {}
    for g in games:
        h, a = club_of(g["home"]), club_of(g["away"])
        if h and a:
            by_pair[(h, a)] = g

    changed = 0
    for ev, st in near:
        g = by_pair.get((ev.get("homeId"), ev.get("awayId")))
        if not g:
            log("No match for %s v %s" % (ev.get("home"), ev.get("away")))
            continue
        new = dict(ev)
        if g["played"] and g["hs"] is not None and g["as"] is not None:
            new.update(state="post", hs=g["hs"], **{"as": g["as"]})
            new.pop("status", None)
        else:
            live = live_score(season, g["code"]) if g["code"] and now >= st - dt.timedelta(minutes=10) else None
            if live:
                hs, a_s, q = live
                new.update(state="in", hs=hs, status=("Q%d" % q if q <= 4 else "OT") if q else "LIVE", **{"as": a_s})
            elif g["hs"] is not None and g["as"] is not None and (g["hs"] or g["as"]):
                new.update(state="in", hs=g["hs"], status="LIVE", **{"as": g["as"]})
        if new != ev:
            ev.clear()
            ev.update(new)
            changed += 1
            log("%s %s-%s %s" % (ev.get("home"), ev.get("hs"), ev.get("as"), ev.get("away")))
    if changed:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(LEAGUE_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    log("%d game(s) checked, %d changed." % (len(near), changed))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never stop the ESPN job
        log("failed: %s" % e)
        sys.exit(0)
