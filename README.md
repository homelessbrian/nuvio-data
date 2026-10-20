# nuvio-data

Data files for the Nuvio + IPTV app, kept up to date by GitHub Actions.

## wrestling.json (wrestling and boxing)

WWE, AEW and TNA shows from yesterday to two weeks ahead, read once a day from
[TheSportsDB](https://www.thesportsdb.com) by `.github/workflows/nuvio-data.yml`. The app reads this
file (it never contacts TheSportsDB itself).

- Text only: show name, league, start time (UTC) and venue.
- League logos are included as web addresses on TheSportsDB's image server, never as image files,
  and only for leagues listed in the `WRESTLING_LOGOS` repository variable (or whose logo licence
  TheSportsDB's API states). Check the logo's licence on its TheSportsDB league page before adding it.
- Optional paid key: add it as the `TSDB_KEY` secret. Whole seasons are then read in one request
  per league instead of day by day.

Wrestling schedule data: TheSportsDB.

## football/

Non-league English football (the National League and the leagues below it, which ESPN doesn't
cover), from TheSportsDB. Needs the paid key in the `TSDB_KEY` secret.

- `football/index.json`: the leagues and their teams (the app's Pick Your Teams reads it).
- `football/<league id>.json`: each league's games, from six weeks ago to the end of the season.
- Full update once a day; scores every 15 minutes at UK match times (weekends 11:00 to 22:45 UTC,
  weekday evenings 18:00 to 22:45 UTC), only for leagues with a game on.
- Optional variables: `FOOTBALL_LEAGUES` (extra league ids), `FOOTBALL_SKIP` (ids to leave out),
  `FOOTBALL_LOGOS` (league ids whose club badges you've checked the licence of, or `all`).
  The run summary lists every English league on TheSportsDB with its id.

Football data: TheSportsDB.

## check/ (ESPN check)

`.github/workflows/espn-check.yml` runs the app's Sports code (from Nuvio_Testing's dev branch)
against ESPN's feeds for every league and writes a report in the run summary. Run it by hand
from the Actions tab. It changes nothing.
