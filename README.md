# nuvio-data

Data files for the Nuvio + IPTV app, kept up to date by GitHub Actions
(`.github/workflows/nuvio-data.yml`). The app only reads these files; it never contacts
TheSportsDB itself, so the key stays here.

## leagues.txt: every sport from TheSportsDB

One line per league. **To add a league or a whole new sport, add a line and commit.** After the next
daily run (or press Run workflow in the Actions tab) it's on everyone's Sports page. To remove one,
delete its line or put `#` in front of it. The top of the file explains the optional extras
(where it's shown, how TV guides name it, logos...).

The run's Summary page lists what each line found on TheSportsDB, with ids, and suggests names
when a line isn't found.

The only setting is the `TSDB_KEY` secret (your paid TheSportsDB key).

## sportsdb/

What the app reads:

- `sportsdb/index.json`: every league, its sport, where it's shown, and its teams.
- `sportsdb/<league id>.json`: its games (team sports, with scores and the table) or events
  (races, fight cards, wrestling shows), from a few weeks back to the end of the season.
- Full update once a day; scores every 15 minutes, only for leagues with a game on.

## wrestling.json and football/ (older app versions)

The files older versions of the app read. They're still made until everyone has the new
version; then the two "Older app versions" steps in the workflow (and `scripts/wrestling.py`,
`scripts/football.py`) can be deleted. Their old optional variables (`WRESTLING_LEAGUES`,
`FOOTBALL_LEAGUES`, `OTHER_SPORTS`...) only affect these old files.

## check/ (ESPN check)

`.github/workflows/espn-check.yml` runs the app's Sports code (from Nuvio_Testing's dev branch)
against ESPN's feeds for every league and writes a report in the run summary. Run it by hand
from the Actions tab. It changes nothing.

## espn/ and espn-leagues.txt: a shared cache of ESPN's own scoreboard

Every installed copy of the app used to ask ESPN directly for its region's leagues' scores, over
and over, every few minutes. `.github/workflows/espn-schedule.yml` now asks once, every 5
minutes, for every league in `espn-leagues.txt`, and writes the raw answers to `espn/*.json`; the
app reads that file first and only asks ESPN itself for a league this cache hasn't reached yet,
or a live game it needs sooner than the cache's own refresh.

- `espn-leagues.txt`: one line per league, `<app league id>|<ESPN path>|<extra query string>`.
  Add a line here to add a league to the shared cache; see the notes at the top of the file for
  which leagues don't belong here (the ones ESPN's plain scoreboard endpoint doesn't cover).
- `espn/<league id>.json`: that league's ESPN scoreboard for yesterday to a week ahead, as ESPN
  itself returns it (uninterpreted) - the app parses it exactly as it always has. Yesterday,
  today and tomorrow refresh every few minutes; the rest of the week-ahead window every few
  hours, which is plenty for a schedule that isn't a live score.
- This is new and additive: it changes nothing in `sportsdb/`, `wrestling.json` or `football/`,
  so an app version from before this existed keeps working exactly as it did.

Sports data: TheSportsDB (thesportsdb.com); ESPN's own unofficial, unauthenticated scoreboard.
