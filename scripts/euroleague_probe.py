#!/usr/bin/env python3
"""Prints what the official EuroLeague feeds really return (run by hand from the Actions tab)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import euroleague as e
import datetime as dt

season = e.season_code(dt.datetime.now(dt.timezone.utc))
urls = ["%s/v2/competitions/E/seasons/%s/games" % (e.API, season),
        "%s/v1/schedules?seasonCode=%s" % (e.API, season),
        "%s/v1/results?seasonCode=%s" % (e.API, season)]
for u in urls:
    print("=== " + u)
    try:
        t = e.get(u)
        print(len(t), "bytes; start:", t[:1500].replace("\n", " "))
        try:
            d = json.loads(t)
            games = [g for g in e.walk(d) if any(k.lower() in ("home", "hometeam") for k in g)]
            print("games found:", len(games))
            if games:
                print("sample:", json.dumps(games[0])[:900])
                print("last:", json.dumps(games[-1])[:900])
        except Exception as x:
            print("not json:", x)
    except Exception as x:
        print("failed:", x)
for code in (1, 90, 95, 100):
    u = "%s/api/PlayByPlay?gamecode=%d&seasoncode=%s" % (e.LIVE, code, season)
    print("=== " + u)
    try:
        t = e.get(u)
        print(len(t), "bytes; start:", t[:600].replace("\n", " "))
        d = json.loads(t)
        print("keys:", list(d)[:20] if isinstance(d, dict) else type(d))
        for k in ("FirstQuarter", "ForthQuarter", "FourthQuarter", "ExtraTime"):
            if isinstance(d, dict) and d.get(k):
                print(k, "n=%d last play:" % len(d[k]), json.dumps(d[k][-1])[:500])
        print("parsed:", e.live_score(season, code))
    except Exception as x:
        print("failed:", x)

# End to end on a copy of the league file, with the clock set to last night's games.
import shutil, tempfile
tmp = os.path.join(tempfile.mkdtemp(), "4546.json")
shutil.copy(e.LEAGUE_FILE, tmp)
before = {x["id"]: dict(x) for x in json.load(open(tmp))["events"]}
e.LEAGUE_FILE = tmp
class _D(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return dt.datetime(2026, 11, 11, 21, 30, tzinfo=tz)
e.dt.datetime = _D
print("=== end to end, clock set to 2026-11-11 21:30 UTC")
e.main()
for x in json.load(open(tmp))["events"]:
    if before[x["id"]] != x:
        print("BEFORE", {k: before[x["id"]].get(k) for k in ("home", "away", "state", "hs", "as", "status")})
        print("AFTER ", {k: x.get(k) for k in ("home", "away", "state", "hs", "as", "status")})
