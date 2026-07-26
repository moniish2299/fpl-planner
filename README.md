# FPL Planner

A small toolkit for planning a Fantasy Premier League team: pulls player,
team, and fixture data from the official FPL API, plus underlying xG/xA
stats from Understat, and caches it locally for analysis.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Fetch the latest data (players, teams, fixtures, Understat stats):

```bash
python -m fpl_planner.cli fetch
```

To also pull your own squad, set your FPL team/entry ID (found in the URL
when viewing your team on the FPL site, e.g.
`fantasy.premierleague.com/entry/<id>/event/1`):

```bash
export FPL_TEAM_ID=1234567
python -m fpl_planner.cli fetch
```

or pass it directly:

```bash
python -m fpl_planner.cli fetch --team-id 1234567
```

Fetched data is cached as JSON under `data/`:

- `bootstrap.json` — all players, teams, positions, gameweeks
- `fixtures.json` — full fixture list with difficulty ratings
- `understat.json` — underlying xG/xA/npxG stats per player
- `entry_<id>.json`, `entry_<id>_history.json`, `entry_<id>_picks.json` —
  your own team, season history, and current picks (if `FPL_TEAM_ID` is set)

These files are gitignored since they're just a local cache — re-run
`fetch` to refresh them.

## Data sources

- [Official FPL API](https://fantasy.premierleague.com/api/) — no auth
  required.
- [Understat](https://understat.com/league/EPL) — free, scraped for
  expected-goals/assists data not available in the official API.

## Next steps

Analysis on top of this data (value scores, fixture-adjusted rankings,
transfer suggestions based on your current squad) is planned as a
follow-up once the data layer is in place.
