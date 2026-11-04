#!/usr/bin/env python3
"""
Players for the Nuvio + IPTV Sports page: every team of the leagues in players.txt, with its
players (number, position, country, birth date, height, weight, photo, a short bio) from TheSportsDB.
The app only reads these files, so the TheSportsDB key stays in this repo's secrets.

  python scripts/players.py           Fill in teams that are missing or over a week old (as many as fit
                                      in the run's time), then rebuild the index.
  python scripts/players.py --check   Say what each line of players.txt finds and how many teams are
                                      missing; writes nothing.

Files:
  sportsdb/players/index.json     Every team that has players: id, name, other names, sport, league.
  sportsdb/players/<team id>.json One team's players.

Settings: only the TSDB_KEY secret. Standard library only.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sportsdb as S  # noqa: E402  (the same key, spacing, retries and league lookup as the daily update)

LIST_FILE = "players.txt"
OUT_DIR = os.path.join(S.OUT_DIR, "players")
INDEX = os.path.join(OUT_DIR, "index.json")
STALE_DAYS = 7
MAX_PLAYERS = 120
CHECK = "--check" in sys.argv
S.BUDGET_SECONDS = 12 * 60          # the daily update has the rest of the job's time
NOW = dt.datetime.utcnow()


def stamp():
    return NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(path):
    try:
        with open(path, encoding="utf-8") as f:
            made = dt.datetime.strptime(json.load(f).get("made", ""), "%Y-%m-%dT%H:%M:%SZ")
        return (NOW - made).total_seconds() / 86400.0
    except (OSError, ValueError):
        return None


def teams_of(leagues):
    """[(team id, name, other names, sport, league name)], each team once."""
    out, seen = [], set()
    for lid, item in leagues:
        info = (S.rows_of(S.get("lookupleague.php?id=%s" % lid), "leagues") or [{}])[0] or {}
        lname = S.clean_name(info.get("strLeague") or item.get("name") or lid)
        for t in S.team_rows(lid, info.get("strLeague") or lname):
            tid = str(t.get("idTeam") or "").strip()
            name = (t.get("strTeam") or "").strip()
            if not tid or not name or tid in seen:
                continue
            seen.add(tid)
            alts = [a for a in S.split_list(t.get("strTeamAlternate") or t.get("strAlternate")) if a and a != name]
            out.append((tid, name, alts[:4], (t.get("strSport") or info.get("strSport") or "").strip(), lname))
    return out


def player_rows(tid):
    d = S.get("lookup_all_players.php?id=%s" % tid, quiet404=True)
    rows = S.rows_of(d, "player", "players")
    if not rows and d is None:
        rows = S.rows_of(S.get("list/players/%s" % tid, v2=True, quiet404=True), "list", "players", "player")
    return rows


def short(v, n):
    v = " ".join((v or "").split())
    return v[:n] if v else None


def compact(p):
    name = (p.get("strPlayer") or "").strip()
    if not name or (p.get("strStatus") or "").strip().lower() in ("retired", "deceased"):
        return None
    img = (p.get("strThumb") or p.get("strCutout") or p.get("strRender") or "").strip()
    born = (p.get("dateBorn") or "").strip()
    out = {
        "id": str(p.get("idPlayer") or ""),
        "n": name,
        "num": short(p.get("strNumber"), 4),
        "pos": short(p.get("strPosition"), 30),
        "nat": short(p.get("strNationality"), 30),
        "born": born if re.match(r"^\d{4}-\d{2}-\d{2}$", born) else None,
        "h": short(p.get("strHeight"), 24),
        "w": short(p.get("strWeight"), 24),
        "side": short(p.get("strSide"), 12),
        "img": img if img.startswith("https://") else None,
        "bio": S.about(p.get("strDescriptionEN")),
    }
    return {k: v for k, v in out.items() if v}


def write_team(team, rows):
    tid, name, alts, sport, league = team
    players = [c for c in (compact(p) for p in rows) if c][:MAX_PLAYERS]
    obj = {"made": stamp(), "team": {"n": name, "s": sport, "l": league}, "players": players}
    if alts:
        obj["team"]["a"] = alts
    S.write_if_changed(os.path.join(OUT_DIR, "%s.json" % tid), obj)
    return len(players)


def build_index():
    teams = []
    for fn in sorted(os.listdir(OUT_DIR)):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        try:
            with open(os.path.join(OUT_DIR, fn), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        t = d.get("team") or {}
        if d.get("players") and t.get("n"):
            e = {"id": fn[:-5], "n": t["n"], "s": t.get("s", ""), "l": t.get("l", ""), "c": len(d["players"])}
            if t.get("a"):
                e["a"] = t["a"]
            teams.append(e)
    made = stamp()
    try:
        with open(INDEX, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("teams") == teams:
            made = old.get("made", made)
    except (OSError, ValueError):
        pass
    S.write_if_changed(INDEX, {"made": made, "teams": teams})
    return len(teams)


def main():
    out = ["## Players" + (" (check: nothing written)" if CHECK else ""), ""]
    if S.FREE:
        out.append("No TSDB_KEY secret: skipped.")
        S.write_summary(out)
        return
    if not os.path.exists(LIST_FILE):
        out.append("players.txt is missing.")
        S.write_summary(out)
        return
    items = S.parse_list(LIST_FILE)
    leagues = S.resolve(items, out)
    teams = teams_of(leagues)
    os.makedirs(OUT_DIR, exist_ok=True)
    todo = []
    for team in teams:
        age = age_days(os.path.join(OUT_DIR, "%s.json" % team[0]))
        if age is None:
            todo.append((9999.0, team))
        elif age >= STALE_DAYS:
            todo.append((age, team))
    todo.sort(key=lambda x: -x[0])
    out.append("")
    out.append("%d league(s), %d team(s); %d to fill in or refresh." % (len(leagues), len(teams), len(todo)))
    S.log(out[-1])
    if CHECK:
        S.write_summary(out)
        return
    done = empty = 0
    for _, team in todo:
        if S.time_left() < 45:
            break
        n = write_team(team, player_rows(team[0]))
        done += 1
        empty += 0 if n else 1
    out.append("Players read for %d team(s) (%d with none listed); %d left for the next run." % (done, empty, len(todo) - done))
    S.log(out[-1])
    out.append("Index: %d team(s) with players." % build_index())
    S.write_summary(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
