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
selected (defaults: `gemini-3.5-flash-lite` / `claude-haiku-4-5-20251001`).

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
- `lineups.json` — predicted/confirmed starting lineups from RotoWire, for
  the GW1 predicted-lineup signal (see below) - refetch this one close to
  kickoff, since it goes stale fast unlike the other two.

Pass `--no-world-cup`, `--no-preseason`, and/or `--no-lineups` to `fetch`
to skip any of these three LLM-assisted fetches individually (e.g. you
already have fresh preseason/World Cup data cached and just want to
refresh the fast-changing lineup predictions, or you'd rather not spend
the LLM calls on a signal you don't plan to use):

```bash
python -m fpl_planner.cli fetch --no-world-cup --no-preseason
```

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

**Top players** — lists the highest-scored players for a given fixture
horizon, without any budget/position-quota/squad constraints - useful for
eyeballing who the scoring model rates before committing to a full squad.

```bash
python -m fpl_planner.cli players --gameweeks 5 --position MID --max-price 8 --top 20
```

**Pre-GW1 draft planner** — solves for the top 5 distinct 15-man squads
(budget/position/max-3-per-team constraints) that maximize a fixture-
adjusted score, using an integer program (PuLP + the bundled CBC solver).
The 15 players are chosen for value across the `--gameweeks` horizon, but
the starting XI/bench split and captain/vice pick within each squad are
optimized separately for the single starting gameweek (`gw1=` in the
output) - a player worth drafting for the next several weeks isn't
necessarily who you'd start or captain in the very first one.

```bash
python -m fpl_planner.cli draft --budget 100
```

To guarantee specific players end up in every returned squad, pass
`--include` (repeatable, or comma-separate multiple names in one flag):

```bash
python -m fpl_planner.cli draft --budget 100 --include Haaland --include "Virgil,Salah"
```

Matching is a global fuzzy name match (last name is usually enough), and
each match is echoed back before the squads print so you can catch a wrong
match. This only guarantees the player is on the 15 - the optimizer still
freely picks the other 14, and still decides the starting XI/bench/captain
on its own (an included player isn't guaranteed to start). If the required
players can't all fit under the budget/position/max-3-per-team constraints
at once, it prints a clear "no feasible squad" error rather than silently
dropping one.

Each squad also gets a **gameweek plan** - a week-by-week simulation across
the `--gameweeks` horizon, printed under that squad's listing:

- **Bench rotation**: each week's starting XI/bench/captain/vice-captain is
  re-picked from that week's fixtures (blank gameweeks zero a player out of
  contention, double gameweeks double their weight), so a player can rotate
  in or out - or take the armband - purely from a fixture swing, with no
  transfer involved.
- **Transfers**: from GW2 on, the single best available transfer that
  gameweek is taken if it's free, or if its point gain over the *remaining*
  horizon outweighs the 4-point hit. Free transfers accumulate by 1 each
  week one isn't used (capped at 5, mirroring FPL's saved-transfer rule).

This only ever considers one transfer per gameweek (no modeling of taking
two hits for a double swap in the same week), and each week's transfer
decision is greedy/best-available rather than jointly optimized across the
whole horizon - it can't see that saving this week's transfer would set up
a much better one two weeks later.

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

### Goalkeeper scoring quirks

The base score weights points-per-game/xGI-per-90/ICT/minutes at
45/25/15/15%. xGI-per-90 (expected goal involvements) is an attacking-output
stat and meaningless for a shot-stopper - in practice almost every keeper
ties at exactly 0.0 for it, so its 25% weight ends up rewarding whichever
handful of keepers have a tiny nonzero rounding artifact there, not real
quality. For GKP specifically, that 25% is folded into points-per-game
instead (70/0/15/15), which actually reflects a keeper's clean
sheets/saves/bonus output.

### No-history backfill

The scoring model leans on last season's stats (points-per-game, xGI/90,
ICT, minutes), which doesn't exist for a new signing, a promoted club's
debutant, or an academy graduate - anyone with 0 minutes last season.
Rather than scoring them as a flat zero (the worst possible player at
their position, which isn't a fair prior for someone who simply hasn't
played in the league yet), those stats are backfilled with a price-weighted
average of their same-team, same-position teammates who do have history -
their price already reflects what the club/market expects of them, so a
similarly-priced teammate's output is a reasonable stand-in. If a club has
nobody with history at that position either (e.g. a newly-promoted side's
entire back line), it falls back to a price-weighted league-wide average
at that position instead of leaving them at zero. This always runs (no
LLM key needed) and applies everywhere `score_players()` is used -
`players`/`draft`/`transfers`/`captain` all flag affected players with
`[backfilled]`. Goalkeepers are the one exception to the "same-team"
tier - see below.

### Backup goalkeepers

A club only ever starts one keeper, unlike DEF/MID/FWD depth where several
teammates genuinely share the pitch. That breaks the backfill above for
GKPs specifically: a team usually has just one keeper with real history, so
"average of same-team, same-position teammates" is really just cloning that
one starter's exact stats onto the backup - making a cheap 2nd-choice
keeper look statistically identical to (and thus a screaming value bargain
next to) an expensive #1, which would otherwise get drafted/transferred in
purely because it looks like free value. To fix that: goalkeepers skip the
same-team backfill tier entirely (they go straight to the league-wide
average), and every keeper who isn't their club's identified #1 - by
last season's minutes, falling back to price when no keeper at that club
has any history at all - gets an explicit score penalty on top, regardless
of backfill. Affected players are flagged `[backup GK]`.

### World Cup fatigue & preseason signals

`draft`/`transfers`/`captain` output flags players with `[WC:<minutes>min]`
and/or `[preseason:<pct>%]` when data is available - these feed into the
score itself (not just the label), so a heavily flagged player scores lower
without you having to notice the flag yourself. Pass `--no-world-cup` and/or
`--no-preseason` to either of those commands to ignore one signal (or both)
even when the cached data is present, if you'd rather judge that yourself.

- **World Cup fatigue**: players who featured in the Final, both Semis, or
  the Third-place match (i.e. the least recovery time before preseason) get
  a score penalty that's largest at GW1 and fades to nothing by GW6. Sourced
  from the main Wikipedia World Cup article directly - a tournament that
  just finished doesn't have separate per-match Wikipedia articles yet
  (those get split out over the following months/years), so this reads the
  one big article in a single LLM call and asks it to focus on the relevant
  sections.
- **Preseason "nailed on" signal**: blends each player's share of their
  club's preseason friendly minutes into the existing minutes-based score
  component (last season's minutes alone otherwise). Sourced from each
  club's BBC Sport team page rather than the club's own site: official club
  sites turned out to be almost entirely JavaScript SPAs (a plain HTTP GET
  returns an empty shell - verified directly, most return under 2KB of real
  text once script/style/svg markup is stripped), which no amount of prompt
  tuning fixes. BBC's team pages are server-rendered, follow one consistent
  URL per club, and already show recent friendly results with inline
  match-report prose where BBC covered the game in writing.

**Real limitations, worth knowing before trusting these:**
- Only friendlies BBC actually wrote a report on carry player-level detail -
  a friendly that's just a bare scoreline on the page contributes to the
  minutes denominator but no player gets credited minutes from it.
- Preseason friendlies are still being played into mid-August, so this data
  is necessarily incomplete until close to GW1 - re-run `fetch` periodically.
- LLM extraction from prose is best-effort, not exact - "minutes_estimate"
  is the model's read of the article, not an official stat.
- Player-name matching against FPL's roster is heuristic (see
  `analysis/player_match.py`); preseason matching is scoped to each club's
  own squad (low false-positive risk), but World Cup matching is global
  (nationality doesn't map to a club), so it's the shakier of the two.
- Each `fetch` run makes one LLM call per club plus a handful for World Cup
  (~20 total) - cheap on a small model, but not free, and it adds real
  wall-clock time to `fetch`.

### Predicted GW1 lineup signal

`draft` also folds in [RotoWire's](https://www.rotowire.com/soccer/lineups.php)
predicted/confirmed Premier League lineups - but **only for GW1 specifically**,
never for the multi-gameweek horizon score used to pick the 15 players, and
never for `transfers`/`captain`. Predicted lineups aren't posted more than a
few days before kickoff, so unlike the World Cup/preseason signals this one
goes stale fast - refetch it close to matchday for it to mean anything.

For a team RotoWire has covered, every squad player is scored as:
- **predicted starter** → no change
- **explicitly OUT** (injured/suspended) → scored at 0 for GW1
- **doubtful/questionable** → scored at 60% for GW1
- **in the squad but not in the predicted XI** (implicit bench/rotation risk,
  since the team's predicted XI is known) → scored at 50% for GW1

A team RotoWire *hasn't* covered at all (too early, a fixture postponement,
or the page's team-name text just didn't match) is different from a
confirmed bench spot - it's "unknown", not "known and left out" - so it
gets a smaller 85% penalty for GW1 rather than either the full 50% bench
penalty or no penalty at all.

This can change which of a squad's 15 starts, who's captain/vice, and (via
the gameweek plan) whether a bench-rotation swap shows up for GW1
specifically - shown in `draft` output as `[lineup:out]`/`[lineup:doubtful]`/
`[lineup:bench]`/`[lineup:unknown]` (predicted starters aren't flagged, to
keep the noise down). Pass `--no-lineups` to ignore it even when cached data
is present.

## Data sources

- [Official FPL API](https://fantasy.premierleague.com/api/) — no auth
  required. Per-player stats (points, ICT, expected goals/assists per 90,
  status/injury flags) drive the player scoring model directly.
- [Understat](https://understat.com/league/EPL) — free, via its internal
  `getLeagueData` JSON endpoint. Used specifically for team-level xG/xGA
  (home/away split) to build the custom FDR, since FPL's own team strength
  fields aren't populated until the season is under way.
- [BBC Sport](https://www.bbc.com/sport/football) team pages and
  [Wikipedia](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup) — no
  structured API for either preseason friendlies or World Cup lineups, so
  these are fetched as plain pages and parsed with an LLM call rather than
  scraped with fixed selectors. See the signals section above for caveats
  (including why BBC rather than official club sites).
- [RotoWire](https://www.rotowire.com/soccer/lineups.php) — predicted/
  confirmed Premier League starting lineups, same plain-page-plus-LLM-call
  approach as the two above. Used only for the GW1-specific signal in
  `draft` (see above) - it's the freshest-but-most-perishable of the three,
  so `fetch` should be re-run close to kickoff for it to be useful.

## Next steps

The scoring model currently leans on last season's underlying stats since
there's no current-season form pre-GW1. Once gameweeks start, a natural
follow-up is blending in current-season form/xG as it accumulates, and
computing free-transfer counts from transfer history instead of passing
`--free-transfers` manually.
