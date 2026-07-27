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

Optional: set an LLM API key to also pull the World Cup fatigue and
preseason "nailed on" signals (see below) - `fetch` skips both cleanly if
one isn't set, everything else works either way.

The default provider is Gemini (has a free tier, good enough for this kind
of simple extraction):

```bash
export GEMINI_API_KEY=...
```

To use Anthropic instead:

```bash
export FPL_PLANNER_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=...
```

`FPL_PLANNER_LLM_API_KEY` also works as a provider-agnostic override, and
`FPL_PLANNER_LLM_MODEL` overrides the model for whichever provider is
selected (defaults: `gemini-2.5-flash-lite` / `claude-haiku-4-5-20251001`).

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

If an LLM API key is set (see Setup above), `fetch` also produces:

- `worldcup.json` — minutes played in the World Cup Final/Semis/Third-place
  match, for the World Cup fatigue signal
- `preseason.json` — per-club preseason friendly appearances/minutes, for
  the "nailed on starter" signal

See **World Cup fatigue & preseason signals** below for what these do and
their real limitations - it's the least reliable part of this tool.

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

### World Cup fatigue & preseason signals

`draft`/`transfers`/`captain` output flags players with `[WC:<minutes>min]`
and/or `[preseason:<pct>%]` when data is available - these feed into the
score itself (not just the label), so a heavily flagged player scores lower
without you having to notice the flag yourself.

- **World Cup fatigue**: players who featured in the Final, both Semis, or
  the Third-place match (i.e. the least recovery time before preseason) get
  a score penalty that's largest at GW1 and fades to nothing by GW6.
  Sourced by finding those match articles from the Wikipedia World Cup page
  and asking an LLM to extract lineups/minutes from them, since there's no
  structured API for this.
- **Preseason "nailed on" signal**: blends each player's share of their
  club's preseason friendly minutes into the existing minutes-based score
  component (last season's minutes alone otherwise). Sourced the same way -
  finding a club's friendly match report links and extracting lineups via
  an LLM - because official match reports are prose news articles with no
  consistent structure across clubs, and neither Transfermarkt's schedule
  pages nor FBref/WhoScored (blocked in the sandbox this was built in, at
  least) turned out to carry this data.

**Real limitations, worth knowing before trusting these:**
- Man City and Man Utd's official sites block scraping outright (403) -
  they're simply missing from `preseason.json`, not zero-filled.
- Preseason friendlies are still being played into mid-August, so this data
  is necessarily incomplete until close to GW1 - re-run `fetch` periodically.
- LLM extraction from prose is best-effort, not exact - "minutes_estimate"
  is the model's read of the article, not an official stat.
- Player-name matching against FPL's roster is heuristic (see
  `analysis/player_match.py`); preseason matching is scoped to each club's
  own squad (low false-positive risk), but World Cup matching is global
  (nationality doesn't map to a club), so it's the shakier of the two.
- Each `fetch` run makes on the order of dozens of LLM calls (1-2 per club
  for preseason, a handful for World Cup) - cheap on a small model, but not
  free, and it add real wall-clock time to `fetch`.

## Data sources

- [Official FPL API](https://fantasy.premierleague.com/api/) — no auth
  required. Per-player stats (points, ICT, expected goals/assists per 90,
  status/injury flags) drive the player scoring model directly.
- [Understat](https://understat.com/league/EPL) — free, via its internal
  `getLeagueData` JSON endpoint. Used specifically for team-level xG/xGA
  (home/away split) to build the custom FDR, since FPL's own team strength
  fields aren't populated until the season is under way.
- Official club websites (fixtures/results pages) and
  [Wikipedia](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup) — no
  structured API for either preseason friendlies or World Cup lineups, so
  these are fetched as plain pages and parsed with an LLM call rather than
  scraped with fixed selectors. See the signals section above for caveats.

## Next steps

The scoring model currently leans on last season's underlying stats since
there's no current-season form pre-GW1. Once gameweeks start, a natural
follow-up is blending in current-season form/xG as it accumulates, and
computing free-transfer counts from transfer history instead of passing
`--free-transfers` manually.
