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
- `understat.json` / `understat_teams.json` — underlying xG/xA/npxG stats
  per player and per team
- `entry_<id>.json`, `entry_<id>_history.json`, `entry_<id>_picks.json` —
  your own team, season history, and current picks (if `FPL_TEAM_ID` is set
  and you've saved a squad — otherwise use `draft` below to build one)

These files are gitignored since they're just a local cache — re-run
`fetch` to refresh them.

### Analysis commands

All of these read from the local cache, so run `fetch` first.

**Custom fixture difficulty (FDR)** — FPL's own team-strength ratings are
blank pre-season, so this is derived from last season's Understat xG/xGA
per team (split home/away). Promoted teams have no top-flight history of
their own, so they're assigned a relegated team's numbers as a proxy.

```bash
python -m fpl_planner.cli fdr --gameweeks 5
```

**Pre-GW1 draft planner** — solves for the 15-man squad (budget/position/
max-3-per-team constraints) that maximizes a fixture-adjusted score, using
an integer program (PuLP + the bundled CBC solver), plus a starting XI and
captain/vice pick.

```bash
python -m fpl_planner.cli draft --budget 100
```

**Transfer suggestions** — for a saved squad (`FPL_TEAM_ID` with picks
fetched), finds the best single swap for each of your players and ranks
them by score gain, flagging which are worth a -4 point hit.

```bash
python -m fpl_planner.cli transfers --team-id 1234567
```

**Captain/vice-captain** — ranks your squad for a specific gameweek,
accounting for blank/double gameweeks (a player whose team plays twice gets
their score doubled; a player whose team doesn't play is excluded).

```bash
python -m fpl_planner.cli captain --team-id 1234567 --gameweek 1
```

**Chip timing** — scans the fixture list for blank/double gameweeks and
recommends Free Hit / Wildcard / Bench Boost / Triple Captain timing around
them. Pre-season the fixture list has no blanks/doubles yet (those appear
once cup fixtures reshuffle the calendar), so you'll get a generic
rule-of-thumb until then.

```bash
python -m fpl_planner.cli chips --team-id 1234567
```

## Data sources

- [Official FPL API](https://fantasy.premierleague.com/api/) — no auth
  required. Per-player stats (points, ICT, expected goals/assists per 90,
  status/injury flags) drive the player scoring model directly.
- [Understat](https://understat.com/league/EPL) — free, via its internal
  `getLeagueData` JSON endpoint. Used specifically for team-level xG/xGA
  (home/away split) to build the custom FDR, since FPL's own team strength
  fields aren't populated until the season is under way.

## Next steps

The scoring model currently leans on last season's underlying stats since
there's no current-season form pre-GW1. Once gameweeks start, a natural
follow-up is blending in current-season form/xG as it accumulates, and
computing free-transfer counts from transfer history instead of passing
`--free-transfers` manually.
