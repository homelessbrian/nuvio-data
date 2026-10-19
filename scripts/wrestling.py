#!/usr/bin/env python3
"""
Makes wrestling.json for the Nuvio + IPTV Sports page: WWE, AEW and TNA shows from yesterday to
two weeks ahead, from TheSportsDB's API. Run once a day by GitHub Actions; the app only ever
reads the file this writes, so TheSportsDB gets about 50 requests a day however many people use
the app.

Text only (show name, league, start time, venue). League logos are included as web addresses
(never the images themselves) only for leagues whose logo licence has been checked, either by
TheSportsDB's own licence field when it has one, or by listing the league in the WRESTLING_LOGOS
repository variable (for example "wwe,aew") after checking the logo's licence on its
TheSportsDB page.

Free key ("123"): the free tier returns at most 3 events per day per league, so the schedule is
read one day at a time. With a paid key in the TSDB_KEY secret, whole seasons are read instead
(one or two requests per league).

Only the Python standard library is used.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY = (os.environ.get("TSDB_KEY") or "").strip() or "123"
FREE = KEY == "123"
BASE = "https://www.thesportsdb.com/api/v1/json/%s/" % KEY
OUT = "wrestling.json"
DAYS_BACK = 1
DAYS_AHEAD = 14
# With the paid key (whole seasons in one request): further ahead. Big wrestling events and
# boxing cards are announced weeks or months out.
AHEAD_PAID = {"boxing": 120}
AHEAD_PAID_DEFAULT = 45
# The free key allows about 30 requests a minute, but GitHub's machines share addresses, so the
# limit is often hit sooner: start at 3.5 seconds apart and slow down further after each "too
# many requests" answer.
GAP = [3.5 if FREE else 0.7]
# The job is stopped by GitHub after 20 minutes: optional extras (the TV channel test) are
# skipped once this many seconds have gone by, so the schedule is always saved.
BUDGET_SECONDS = 11 * 60
STARTED = time.time()


def time_left():
    return BUDGET_SECONDS - (time.time() - STARTED)

# WWE's league on TheSportsDB. The others are looked up by name (their ids aren't fixed here).
KNOWN = {"wwe": "4444"}
FIND = {
    "aew": ["all elite wrestling", "aew"],
    "tna": ["tna wrestling", "tna", "impact wrestling"],
    "boxing": ["boxing"],
}

_last = [0.0]


def get(path, v2=False, quiet404=False):
    """One API request, spaced out, retried on rate limits and server trouble. None on failure."""
    url = ("https://www.thesportsdb.com/api/v2/json/" + path) if v2 else BASE + path
    headers = {"User-Agent": "nuvio-data/1.0 (GitHub Actions)"}
    if v2:
        headers["X-API-KEY"] = KEY
    for attempt in range(4):
        wait = GAP[0] - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8").strip()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                GAP[0] = min(GAP[0] + 1.5, 8.0)
                print("  rate limited: waiting a minute, then %.1f seconds between requests" % GAP[0], flush=True)
                time.sleep(65)
                continue
            if e.code >= 500:
                time.sleep(10)
                continue
            if not (quiet404 and e.code == 404):
                print("  %s: HTTP %s" % (path.split("?")[0], e.code), file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print("  %s: %s" % (path.split("?")[0], e), file=sys.stderr)
            time.sleep(10)
    return None


FIGHTING_NAMES = []


def find_leagues():
    """League key -> TheSportsDB league id. WRESTLING_LEAGUES ("aew=1234,tna=5678") overrides."""
    found = dict(KNOWN)
    data = get("search_all_leagues.php?s=Fighting") or {}
    rows = data.get("countries") or data.get("leagues") or []
    FIGHTING_NAMES[:] = ["%s (%s)" % (r.get("strLeague"), r.get("idLeague")) for r in rows]
    for key, names in FIND.items():
        for row in rows:
            name = (row.get("strLeague") or "").lower()
            alt = (row.get("strLeagueAlternate") or "").lower()
            if any(n == name or n in alt.split(",") or name.startswith(n + " ") or name == n for n in names):
                found[key] = row.get("idLeague")
                break
    for part in (os.environ.get("WRESTLING_LEAGUES") or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip().isdigit():
                found[k.strip().lower()] = v.strip()
    return {k: v for k, v in found.items() if v}


def licence_ok(league):
    """True when TheSportsDB gives the badge a licence that isn't blank or unknown."""
    for k, v in league.items():
        if "licen" in k.lower() and ("badge" in k.lower() or "logo" in k.lower() or k.lower().startswith("strlicen")):
            text = (v or "").strip().lower()
            if text and text not in ("unknown", "none", "null", "0"):
                return True
    return False


BRAND_DROP = {"mens", "men", "womens", "women", "wrestling", "tag", "team", "division", "brand", "the"}


def find_brands(key, lid, league):
    """
    Show brands inside a league and their logos, e.g. WWE's "NXT Mens" team -> {"word": "nxt"}.
    TheSportsDB lists a promotion's brands as its teams. Only used for leagues whose own logo
    is already approved (same owner, same licence check). Men's teams win over women's.
    """
    # Three ways to ask, newest first (not every one is open to every key).
    rows = []
    if not FREE:
        data = get("list/teams/%s" % lid, v2=True, quiet404=True) or {}
        rows = data.get("list") or data.get("teams") or []
    if not rows:
        rows = (get("lookup_all_teams.php?id=%s" % lid, quiet404=True) or {}).get("teams") or []
    if not rows:
        rows = (get("search_all_teams.php?l=%s" % urllib.parse.quote(league.get("strLeague") or key)) or {}).get("teams") or []
    league_words = {key.lower()} | {w.lower() for w in (league.get("strLeague") or "").split()}
    best = {}
    for t in rows:
        badge = (t.get("strBadge") or t.get("strTeamBadge") or "").strip()
        name = (t.get("strTeam") or "").strip()
        if not badge.startswith("https://") or not name:
            continue
        words = [w for w in name.lower().replace("'", "").split() if w not in BRAND_DROP]
        if not words or words[0] in league_words:
            continue
        word = words[0]
        womens = "women" in name.lower()
        if word not in best or (best[word][0] and not womens):
            best[word] = (womens, {"word": word, "name": name, "badge": badge})
    return [v[1] for _, v in sorted(best.items())]


def to_event(key, e):
    if (e.get("strStatus") or "").lower() in ("cancelled", "canceled", "postponed"):
        return None
    name = (e.get("strEvent") or "").strip()
    if not name:
        return None
    stamp = (e.get("strTimestamp") or "").strip()
    date = (e.get("dateEvent") or "").strip()
    time_ = (e.get("strTime") or "").strip()
    has_time = True
    if stamp:
        start = stamp.replace(" ", "T")[:19]
    elif date and time_:
        start = "%sT%s" % (date, time_[:8])
    elif date:
        start = "%sT00:00:00" % date
        has_time = False
    else:
        return None
    try:
        parsed = dt.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return {
        "id": e.get("idEvent") or "%s:%s:%s" % (key, name, start),
        "league": key,
        "name": name,
        "start": parsed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hasTime": has_time,
        "venue": (e.get("strVenue") or "").strip() or None,
        "city": (e.get("strCity") or "").strip() or None,
        "country": (e.get("strCountry") or "").strip() or None,
    }


def main():
    # Show progress in the GitHub log as it happens (not all at the end).
    sys.stdout.reconfigure(line_buffering=True)
    today = dt.datetime.now(dt.timezone.utc).date()
    first = today - dt.timedelta(days=DAYS_BACK)
    last = today + dt.timedelta(days=DAYS_AHEAD)
    approved = {s.strip().lower() for s in (os.environ.get("WRESTLING_LOGOS") or "").split(",") if s.strip()}

    leagues = find_leagues()
    print("Leagues: %s (%s key)" % (leagues, "free" if FREE else "paid"))
    summary = [
        "## Wrestling and boxing schedule", "",
        "WRESTLING_LOGOS setting seen by this run: %s" % (", ".join(sorted(approved)) or "**none** (add it under Settings > Secrets and variables > Actions > Variables)"),
        "", "| League | Shows | Logo |", "|---|---|---|",
    ]
    out_leagues, events = [], []
    for key, lid in leagues.items():
        info = ((get("lookupleague.php?id=%s" % lid) or {}).get("leagues") or [{}])[0] or {}
        badge = (info.get("strBadge") or "").strip()
        logo_note = "none on TheSportsDB"
        use_badge = None
        if badge.startswith("https://"):
            if key in approved or licence_ok(info):
                use_badge = badge
                logo_note = "included"
            else:
                logo_note = "left out (licence not checked: add '%s' to WRESTLING_LOGOS once checked)" % key
        brands = find_brands(key, lid, info) if use_badge and key != "boxing" else []
        if brands:
            logo_note += "; show logos: " + ", ".join(b["name"] for b in brands)
        out_leagues.append({"key": key, "id": lid, "name": info.get("strLeague") or key.upper(),
                            "badge": use_badge, "brands": brands})

        found = []
        last_k = last if FREE else today + dt.timedelta(days=AHEAD_PAID.get(key, AHEAD_PAID_DEFAULT))
        if FREE:
            day = first
            print("Reading %s (%s days)..." % (key.upper(), (last - first).days + 1))
            while day <= last:
                rows = (get("eventsday.php?d=%s&l=%s" % (day.isoformat(), lid)) or {}).get("events") or []
                found += rows
                day += dt.timedelta(days=1)
        else:
            print("Reading %s..." % key.upper())
            for year in sorted({first.year, last_k.year}):
                rows = (get("eventsseason.php?id=%s&s=%s" % (lid, year)) or {}).get("events") or []
                if not rows:
                    # Some leagues name seasons "2026-2027".
                    rows = (get("eventsseason.php?id=%s&s=%d-%d" % (lid, year, year + 1)) or {}).get("events") or []
                found += rows
        n = 0
        for e in found:
            ev = to_event(key, e)
            if ev and first.isoformat() <= ev["start"][:10] <= last_k.isoformat():
                events.append(ev)
                n += 1
        summary.append("| %s | %d | %s |" % (key.upper(), n, logo_note))

    missing = [k for k in FIND if k not in leagues]
    if missing:
        summary.append("")
        summary.append("Not found on TheSportsDB by name: %s. Fighting leagues there: %s. "
                       "To add one, set the WRESTLING_LEAGUES variable, e.g. aew=1234." % (", ".join(missing), "; ".join(FIGHTING_NAMES) or "none listed"))

    # One entry per show, in start order.
    # TheSportsDB sometimes lists one show twice, a day apart ("Dynamite #369" on two dates):
    # the same name in the same league within two days counts once (the earlier listing).
    seen, unique, last_seen = set(), [], {}
    for ev in sorted(events, key=lambda x: (x["start"], x["league"], x["name"])):
        if ev["id"] in seen:
            continue
        seen.add(ev["id"])
        when = dt.datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%SZ")
        key = (ev["league"], " ".join(ev["name"].lower().split()))
        prev = last_seen.get(key)
        if prev is not None and (when - prev) <= dt.timedelta(days=2):
            continue
        last_seen[key] = when
        unique.append(ev)

    old = None
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                old = json.load(f)
        except ValueError:
            old = None

    # Nothing at all this time, but there was a schedule before: TheSportsDB is probably having
    # trouble. Keep the old file rather than wiping the schedule.
    if not unique and old and old.get("events"):
        print("No shows found this time; keeping the previous file.")
        summary.append("")
        summary.append("No shows found this time, so the previous file was kept.")
        write_summary(summary)
        return

    new = {
        "source": "TheSportsDB (thesportsdb.com)",
        "window": {"from": first.isoformat(), "to": last.isoformat()},
        "leagues": out_leagues,
        "events": unique,
    }
    def same(a, b):
        strip = lambda d: {k: v for k, v in (d or {}).items() if k not in ("generated", "window")}
        return strip(a) == strip(b)

    if old is not None and same(old, new):
        print("No changes.")
        summary.append("")
        summary.append("No changes since the last run.")
    else:
        new["generated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("Wrote %d shows." % len(unique))
        summary.append("")
        summary.append("Wrote %d shows (%s to %s)." % (len(unique), first, last))
    write_summary(summary)


def write_summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
