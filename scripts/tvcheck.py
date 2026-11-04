#!/usr/bin/env python3
"""
TV channels check: how many games TheSportsDB lists TV channels for, league by league.

Reads TheSportsDB's TV listings for yesterday to six days ahead, and a few single games per league,
then writes a report in the run's Summary page. It writes no files, so the app isn't affected.
Used to decide whether the daily update should save each game's channels for the app.

  python scripts/tvcheck.py

Settings: only the TSDB_KEY secret (your paid TheSportsDB key).
"""
import collections
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sportsdb as S  # noqa: E402  (the same key, spacing and retries as the daily update)

DAYS_BACK = 1
DAYS_AHEAD = 6
SAMPLE_PER_LEAGUE = 3
# Big leagues the app gets from ESPN, with ESPN's channel lists: for comparison only.
COMPARE = {"4391": "NFL", "4387": "NBA", "4424": "MLB", "4380": "NHL", "4328": "Premier League",
           "4346": "MLS", "4335": "La Liga", "4370": "Formula 1"}


def tv_rows(data):
    return S.rows_of(data, "tvevents", "tvevent", "filter", "lookup", "events", "tv")


def channel(r):
    return (r.get("strChannel") or r.get("strTVStation") or "").strip()


def country(r):
    return (r.get("strCountry") or "").strip() or "?"


def our_leagues():
    try:
        idx = json.load(open(os.path.join(S.OUT_DIR, "index.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    leagues = {str(l["id"]): l.get("name") or str(l["id"]) for l in idx.get("leagues", [])}
    # Each league's games in the checked days: game id -> league id.
    lo = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS_BACK)
    hi = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=DAYS_AHEAD + 1)
    games = {}
    for lid in leagues:
        try:
            d = json.load(open(os.path.join(S.OUT_DIR, lid + ".json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for g in (d.get("games") or []) + (d.get("events") or []):
            try:
                t = dt.datetime.fromisoformat(str(g.get("start", "")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if lo <= t <= hi and g.get("id"):
                games[str(g["id"])] = lid
    return leagues, games


def day_listing(day):
    """One day's TV listings, trying TheSportsDB's newer address first. (rows, which address)"""
    d = S.get("filter/tv/day/%s" % day, v2=True, quiet404=True)
    rows = tv_rows(d)
    if rows:
        return rows, "v2 filter/tv/day"
    d = S.get("eventstv.php?d=%s" % day, quiet404=True)
    rows = tv_rows(d)
    return rows, ("v1 eventstv" if rows else None)


def game_listing(event_id):
    d = S.get("lookup/event_tv/%s" % event_id, v2=True, quiet404=True)
    rows = tv_rows(d)
    if rows:
        return rows
    return tv_rows(S.get("lookuptv.php?id=%s" % event_id, quiet404=True))


def main():
    out = ["# TV channels check (TheSportsDB)", ""]
    if S.FREE:
        out.append("**No TSDB_KEY secret found: this used the free key, which has no TV listings.**")
        out.append("")
    leagues, games = our_leagues()
    # The listings don't say which league a game is in: the comparison leagues' games are read
    # from their seasons, so their listings can be counted by game.
    lo = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).isoformat()
    hi = (dt.date.today() + dt.timedelta(days=DAYS_AHEAD)).isoformat()
    for lid in COMPARE:
        info = (S.rows_of(S.get("lookupleague.php?id=%s" % lid), "leagues") or [{}])[0]
        rows, _ = S.season_events(lid, info, dt.date.today())
        for r in rows:
            if lo <= (r.get("dateEvent") or "") <= hi and r.get("idEvent"):
                games[str(r["idEvent"])] = lid
    today = dt.date.today()
    days = [(today + dt.timedelta(days=i)).isoformat() for i in range(-DAYS_BACK, DAYS_AHEAD + 1)]

    all_rows, used, field_names = [], set(), set()
    for day in days:
        rows, how = day_listing(day)
        S.log("%s: %d listings (%s)" % (day, len(rows), how or "none"))
        if how:
            used.add(how)
        for r in rows:
            field_names.update(k for k, v in r.items() if v not in (None, ""))
        all_rows += rows

    out.append("Days: %s to %s. Listings found: **%d** (%s)." % (days[0], days[-1], len(all_rows), ", ".join(sorted(used)) or "no address answered"))
    out.append("")
    if field_names:
        out.append("Fields in a listing: " + ", ".join(sorted(field_names)))
        out.append("")

    # Group listings by league: TheSportsDB's league id when the listing has one, else the game id.
    by_league = collections.defaultdict(lambda: {"games": set(), "channels": collections.Counter(), "countries": collections.Counter()})
    names = dict(COMPARE)
    for r in all_rows:
        lid = str(r.get("idLeague") or "") or games.get(str(r.get("idEvent") or ""), "")
        if not lid:
            continue
        if r.get("strLeague"):
            names.setdefault(lid, r["strLeague"])
        b = by_league[lid]
        b["games"].add(str(r.get("idEvent") or r.get("strEvent")))
        if channel(r):
            b["channels"][channel(r)] += 1
        b["countries"][country(r)] += 1

    games_per_league = collections.Counter(games.values())

    def row(lid, name, sample=""):
        b = by_league.get(lid)
        total = games_per_league.get(lid)
        listed = len(b["games"]) if b else 0
        share = ("%d of %d" % (min(listed, total), total)) if total else str(listed)
        chans = ", ".join(c for c, _ in b["channels"].most_common(6)) if b else ""
        ctry = ", ".join("%s %d" % (c, n) for c, n in b["countries"].most_common(4)) if b else ""
        return "| %s | %s | %s | %s | %s |" % (name, share, ctry, chans, sample)

    out += ["## The app's TheSportsDB leagues", "",
            "Games with channels = games in these days that have at least one TV listing.", "",
            "| League | Games with channels | Countries | Channels (most listed) | Single-game check |",
            "|---|---|---|---|---|"]
    by_game = collections.defaultdict(list)
    for gid, lid in games.items():
        by_game[lid].append(gid)
    for lid, name in sorted(leagues.items(), key=lambda kv: kv[1].lower()):
        sample = ""
        ids = sorted(by_game.get(lid, []))[:SAMPLE_PER_LEAGUE]
        if ids and S.time_left() > 60:
            hits = sum(1 for i in ids if game_listing(i))
            sample = "%d of %d" % (hits, len(ids))
        out.append(row(lid, name, sample))

    out += ["", "## For comparison: leagues the app gets from ESPN", "",
            "| League | Games with channels | Countries | Channels (most listed) | |", "|---|---|---|---|---|"]
    for lid, name in COMPARE.items():
        out.append(row(lid, name))

    sports = collections.Counter((r.get("strSport") or "?") for r in all_rows)
    out += ["", "## Listings by sport", "", ", ".join("%s %d" % (c, n) for c, n in sports.most_common(20))]
    for lid in ["4328", "4391", "4387"]:
        b = by_league.get(lid)
        if not b:
            continue
        parts = []
        for c, _ in b["countries"].most_common(10):
            chans = sorted({channel(r) for r in all_rows if country(r) == c and games.get(str(r.get("idEvent"))) == lid})
            parts.append("%s: %s" % (c, ", ".join(chans[:6])))
        out += ["", "**%s channels by country:** " % COMPARE[lid] + "; ".join(parts)]
    countries = collections.Counter(country(r) for r in all_rows)
    out += ["", "## Listings by country", "", ", ".join("%s %d" % (c, n) for c, n in countries.most_common(25)) or "none"]

    others = [(lid, b) for lid, b in by_league.items() if lid not in leagues and lid not in COMPARE]
    if others:
        out += ["", "## Other leagues with listings (top 25)", ""]
        for lid, b in sorted(others, key=lambda kv: -len(kv[1]["games"]))[:25]:
            out.append("- %s (%s): %d games" % (names.get(lid, lid), lid, len(b["games"])))

    S.write_summary(out)
    print("\n".join(out))


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
