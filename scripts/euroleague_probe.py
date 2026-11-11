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
