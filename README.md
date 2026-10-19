# nuvio-data

Data files for the Nuvio + IPTV app, kept up to date by GitHub Actions.

## wrestling.json

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
