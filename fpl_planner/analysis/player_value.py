from fpl_planner.analysis import player_match
from fpl_planner.analysis import teams as teams_module
from fpl_planner.analysis.fdr import build_team_strength, fixture_ratings, upcoming_team_fdr

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Status codes FPL uses on elements: a=available, d=doubtful, i=injured,
# s=suspended, u=unavailable (left club/not in squad), n=not available (loan etc).
_UNAVAILABLE_STATUSES = {"u", "n", "s"}

# World Cup fatigue only matters for the first few gameweeks - by GW6 a
# player's had a normal preseason-length turnaround regardless.
_FATIGUE_WINDOW_GWS = 5

# Preseason friendly minutes are the best "nailed on" signal before any real
# season minutes exist, but stop being useful the moment real minutes do -
# fully faded out by 3 full matches' worth of actual season minutes.
_PRESEASON_FADE_MINUTES = 270


def _percentile_ranks(values):
    """values: {id: float}. Returns {id: 0..1 percentile rank}, higher is better."""
    ids = list(values.keys())
    if not ids:
        return {}
    sorted_vals = sorted(values.values())
    n = len(sorted_vals)
    ranks = {}
    for i in ids:
        v = values[i]
        below = sum(1 for x in sorted_vals if x < v)
        ranks[i] = below / n if n else 0.0
    return ranks


def _availability_multiplier(element):
    status = element.get("status", "a")
    if status in _UNAVAILABLE_STATUSES:
        return 0.0
    chance = element.get("chance_of_playing_next_round")
    if chance is not None:
        return chance / 100.0
    if status in ("d", "i"):
        return 0.5
    return 1.0


def _fixture_multiplier(team_fdr, position_id):
    if team_fdr is None:
        return 1.0
    attack_fdr = team_fdr["attack"]
    defense_fdr = team_fdr["defense"]
    if position_id == 4:  # FWD
        fdr = attack_fdr
    elif position_id == 3:  # MID
        fdr = 0.7 * attack_fdr + 0.3 * defense_fdr
    else:  # DEF, GKP
        fdr = 0.3 * attack_fdr + 0.7 * defense_fdr
    # fdr ranges 1 (easiest) to 5 (hardest); center the multiplier on fdr==3
    return 1 + (3 - fdr) * 0.08


def _world_cup_fatigue_multiplier(wc_minutes, from_event):
    """Tiered, decaying penalty for players who went deep in a World Cup that
    finished shortly before the season - a heavy penalty at GW1, fading to
    none by _FATIGUE_WINDOW_GWS gameweeks in."""
    if not wc_minutes or from_event > _FATIGUE_WINDOW_GWS:
        return 1.0
    if wc_minutes >= 450:
        base_penalty = 0.15
    elif wc_minutes >= 250:
        base_penalty = 0.08
    else:
        return 1.0
    fade = max(0.0, (_FATIGUE_WINDOW_GWS - (from_event - 1)) / _FATIGUE_WINDOW_GWS)
    return 1 - base_penalty * fade


def _preseason_blend_weight(real_minutes):
    """Weight given to the preseason fraction in the minutes component,
    linearly faded from 0.6 (no real season minutes yet) to 0.0 (>=3 full
    matches of real minutes this season) - `real_minutes` should be this
    player's own raw current-season minutes (not a backfilled proxy), so a
    player who simply hasn't featured yet doesn't get faded off preseason
    just because other players' gameweeks have passed."""
    fade = max(0.0, 1 - real_minutes / _PRESEASON_FADE_MINUTES)
    return 0.6 * fade


def _as_minutes(value):
    """preseason.json/worldcup.json are LLM-extracted and loaded from disk -
    treat minutes_estimate as untrusted external input even though the
    extractor is supposed to coerce it to a number, since a cache file
    written before that fix (or hand-edited) could still hold a string."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _preseason_fractions(elements, teams_by_id, preseason_data):
    """preseason_data: {team_name: {"appearances": [{"name", "minutes_estimate"}],
    "matches_covered": int}}, as cached by fetch/preseason.py. Matching is
    scoped to each team's own squad, so name collisions across clubs aren't a
    risk. Returns {player_id: fraction 0..1 of available preseason minutes played}.
    """
    if not preseason_data:
        return {}

    by_team = {}
    for e in elements:
        by_team.setdefault(teams_by_id[e["team"]]["name"], []).append(e)

    fractions = {}
    for team_name, data in preseason_data.items():
        matches_covered = data.get("matches_covered", 0)
        candidates = by_team.get(team_name, [])
        if not candidates or not matches_covered:
            continue
        matched, _unmatched = player_match.match_all(candidates, data.get("appearances", []))
        totals = {}
        for entry, candidate in matched:
            totals[candidate["id"]] = totals.get(candidate["id"], 0) + _as_minutes(entry.get("minutes_estimate"))
        available_minutes = matches_covered * 90
        for pid, minutes in totals.items():
            fractions[pid] = min(1.0, minutes / available_minutes)
    return fractions


def _world_cup_minutes_by_player(elements, world_cup_data):
    """world_cup_data: [{"name", "team", "minutes_estimate"}, ...] from
    fetch/worldcup.py. Matched globally (no club to scope by, since squad
    club != international team), so a higher min_score is used to require
    more than a bare surname hit before trusting the match."""
    if not world_cup_data:
        return {}
    matched, _unmatched = player_match.match_all(elements, world_cup_data, min_score=1.5)
    minutes = {}
    for entry, candidate in matched:
        minutes[candidate["id"]] = max(minutes.get(candidate["id"], 0), _as_minutes(entry.get("minutes_estimate")))
    return minutes


_LINEUP_MULTIPLIERS = {"starting": 1.0, "doubtful": 0.6, "unknown": 0.85, "bench": 0.5, "out": 0.0}

# A club fields exactly one starting keeper - unlike DEF/MID/FWD depth, a
# 2nd/3rd choice keeper essentially never plays outside injury/suspension to
# the starter, so even a fair statistical score for one would still make the
# draft/transfer optimizer chase them as "bargains". Penalize anyone at a
# club who isn't that club's identified #1.
BACKUP_GOALKEEPER_MULT = 0.25


def _primary_goalkeeper_ids(elements):
    """Identify each team's starting keeper by last-season minutes (the
    clearest evidence of who actually played), falling back to price (the
    market/club's own read on pecking order) when no keeper at that club has
    any history at all - e.g. a promoted club fielding an entirely new pair.
    """
    by_team = {}
    for e in elements:
        if e["element_type"] == 1:
            by_team.setdefault(e["team"], []).append(e)

    primary_ids = set()
    for keepers in by_team.values():
        with_minutes = [k for k in keepers if float(k.get("minutes") or 0) > 0]
        pool = with_minutes or keepers
        best = max(pool, key=lambda k: (float(k.get("minutes") or 0), k["now_cost"]))
        primary_ids.add(best["id"])
    return primary_ids


def _match_team_candidates(team_name, by_norm_team):
    """team_name is external prose (RotoWire's own team naming) - normalize
    and fall back to substring matching, same as analysis/teams.py's
    Understat team matching, since external sources spell club names
    differently ("Tottenham Hotspur" vs FPL's "Spurs")."""
    norm = teams_module.normalize(team_name)
    if norm in by_norm_team:
        return by_norm_team[norm]
    for norm_fpl, candidates in by_norm_team.items():
        if norm in norm_fpl or norm_fpl in norm:
            return candidates
    return None


def _lineup_status_by_player(elements, teams_by_id, lineup_data):
    """lineup_data: [{"team", "starters": [names], "out": [names],
    "doubtful": [names]}, ...] from fetch/lineups.py (RotoWire predicted
    lineups) - only meaningful for the very next unplayed gameweek, so
    callers should only pass this in for that gameweek's scoring, not a
    multi-gameweek horizon average. Matching is scoped to each team's own
    squad, same low-false-positive approach as the preseason signal.
    Returns {player_id: "starting"|"doubtful"|"bench"|"out"} - a player
    absent from this dict (their club wasn't covered/matched on the page at
    all) is treated as "unknown" by score_players, distinct from "bench"
    (club's lineup is known and they're just not in it).
    """
    if not lineup_data:
        return {}

    by_norm_team = {}
    for e in elements:
        norm = teams_module.normalize(teams_by_id[e["team"]]["name"])
        by_norm_team.setdefault(norm, []).append(e)

    status = {}
    for team_data in lineup_data:
        candidates = _match_team_candidates(team_data.get("team", ""), by_norm_team)
        if not candidates:
            continue

        # default: this team's predicted XI is known, so anyone in its squad
        # not otherwise flagged is an implicit bench/rotation risk.
        for c in candidates:
            status[c["id"]] = "bench"

        # apply weakest signal first so a stronger one (doubtful, then out)
        # overrides it if a player is somehow flagged more than one way
        for name in team_data.get("starters") or []:
            match = player_match.match_player(candidates, name)
            if match:
                status[match["id"]] = "starting"
        for name in team_data.get("doubtful") or []:
            match = player_match.match_player(candidates, name)
            if match:
                status[match["id"]] = "doubtful"
        for name in team_data.get("out") or []:
            match = player_match.match_player(candidates, name)
            if match:
                status[match["id"]] = "out"

    return status


_BACKFILL_FIELDS = ("points_per_game", "expected_goal_involvements_per_90", "ict_index", "minutes")


def _has_historical_data(e):
    return float(e.get("minutes") or 0) > 0


def _price_weighted_average(candidates, field):
    total_weight = sum(c["now_cost"] for c in candidates)
    if not total_weight:
        return None
    return sum(float(c[field] or 0) * c["now_cost"] for c in candidates) / total_weight


def _backfill_stats(elements):
    """Players with zero minutes last season - new signings, promoted-team
    debutants, academy graduates - have no real history to score off of;
    defaulting them to literal zeros judges them as the worst possible
    player at their position, which isn't a fair prior. Substitute a
    price-weighted average of same-team, same-position teammates' stats
    instead (their price already reflects the club/market's expectation of
    them), falling back to a price-weighted league-wide average at that
    position if their club has nobody with history there either (e.g. a
    fully rebuilt back line at a promoted club).

    Returns {player_id: {field: value}} for only the backfilled players,
    covering points_per_game/xGI-per-90/ICT/minutes.
    """
    with_history = [e for e in elements if _has_historical_data(e)]

    by_team_position, by_position = {}, {}
    for e in with_history:
        by_team_position.setdefault((e["team"], e["element_type"]), []).append(e)
        by_position.setdefault(e["element_type"], []).append(e)

    backfilled = {}
    for e in elements:
        if _has_historical_data(e):
            continue
        if e["element_type"] == 1:
            # Squads carry only 1-2 keepers, so "team+position average" is
            # really just cloning the other keeper's exact stats onto this
            # one (see _primary_goalkeeper_ids) - go straight to the
            # league-wide tier instead of a fake per-team average.
            candidates = by_position.get(e["element_type"])
        else:
            candidates = by_team_position.get((e["team"], e["element_type"])) or by_position.get(e["element_type"])
        if not candidates:
            continue
        stats = {}
        for field in _BACKFILL_FIELDS:
            value = _price_weighted_average(candidates, field)
            if value is not None:
                stats[field] = value
        if stats:
            backfilled[e["id"]] = stats
    return backfilled


def build_player_table(bootstrap, preseason_fractions=None, backfilled_stats=None):
    """Merge FPL per-player stats with custom fixture difficulty into a single
    scored table. `points_per_game`/`expected_goal_involvements_per_90`/
    `ict_index`/`minutes` are read straight off the live bootstrap payload,
    so once real gameweeks have been played this is real current-season
    form, not last season's; pre-GW1 those fields are just 0 for almost
    everyone, which is why the preseason/backfill substitutes below exist.
    The fixture multiplier is the only forward-looking adjustment. When
    preseason_fractions has an entry for a player, it's blended into the
    minutes component as a "nailed on" signal, weighted by
    `_preseason_blend_weight` so it fades out as this player accumulates
    real season minutes rather than staying fixed all season.
    `backfilled_stats` (see _backfill_stats) substitutes a price-weighted
    teammate average for any player with zero minutes this season so far,
    instead of scoring them as a flat zero across every stat.
    """
    preseason_fractions = preseason_fractions or {}
    backfilled_stats = backfilled_stats or {}
    elements = bootstrap["elements"]

    def stat(e, field):
        backfill = backfilled_stats.get(e["id"])
        if backfill and field in backfill:
            return backfill[field]
        return float(e[field] or 0)

    by_position = {}
    for e in elements:
        by_position.setdefault(e["element_type"], []).append(e)

    base_scores = {}
    for pos, players in by_position.items():
        ppg = _percentile_ranks({p["id"]: stat(p, "points_per_game") for p in players})
        xgi90 = _percentile_ranks({p["id"]: stat(p, "expected_goal_involvements_per_90") for p in players})
        ict = _percentile_ranks({p["id"]: stat(p, "ict_index") for p in players})
        minutes_pct = _percentile_ranks({p["id"]: stat(p, "minutes") for p in players})
        # xGI/90 is an attacking-involvement stat - meaningless for a
        # shot-stopper, and most keepers tie at exactly 0.0 for it, so its
        # 25% weight ends up rewarding rounding noise rather than quality.
        # Fold that weight into points-per-game instead, which already
        # captures a keeper's actual output (clean sheets/saves/bonus).
        if POSITIONS.get(pos) == "GKP":
            ppg_weight, xgi_weight = 0.70, 0.0
        else:
            ppg_weight, xgi_weight = 0.45, 0.25
        for p in players:
            pid = p["id"]
            if pid in preseason_fractions:
                real_minutes = float(p.get("minutes") or 0)
                preseason_weight = _preseason_blend_weight(real_minutes)
                minutes_component = (
                    (1 - preseason_weight) * minutes_pct[pid] + preseason_weight * preseason_fractions[pid]
                )
            else:
                minutes_component = minutes_pct[pid]
            base_scores[pid] = (
                ppg_weight * ppg[pid]
                + xgi_weight * xgi90[pid]
                + 0.15 * ict[pid]
                + 0.15 * minutes_component
            ) * 100

    return base_scores


def score_players(bootstrap, fixtures, understat_teams, num_gameweeks=5, from_event=1,
                   preseason_data=None, world_cup_data=None, lineup_data=None):
    """Full pipeline: team strength -> fixture ratings -> upcoming FDR ->
    per-player composite score/value. Returns a list of player dicts sorted
    by score descending. `preseason_data`/`world_cup_data`/`lineup_data` are
    all optional - each falls back to no adjustment when not supplied (e.g.
    no LLM API key configured for the LLM-assisted fetch that produces
    them). `lineup_data` (RotoWire predicted lineups) is only meaningful for
    the very next unplayed gameweek - callers should only pass it in for a
    single-gameweek score_players() call for that gameweek, not a
    multi-gameweek horizon average.
    """
    strength = build_team_strength(bootstrap, understat_teams)
    ratings = fixture_ratings(fixtures, strength)
    team_fdr = upcoming_team_fdr(ratings, num_gameweeks=num_gameweeks, from_event=from_event)

    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    preseason_fractions = _preseason_fractions(bootstrap["elements"], teams_by_id, preseason_data)
    wc_minutes_by_id = _world_cup_minutes_by_player(bootstrap["elements"], world_cup_data)
    lineup_status_by_id = _lineup_status_by_player(bootstrap["elements"], teams_by_id, lineup_data)
    backfilled_stats = _backfill_stats(bootstrap["elements"])
    primary_gk_ids = _primary_goalkeeper_ids(bootstrap["elements"])

    base_scores = build_player_table(bootstrap, preseason_fractions, backfilled_stats)

    players = []
    for e in bootstrap["elements"]:
        pid = e["id"]
        fdr_for_team = team_fdr.get(e["team"])
        fixture_mult = _fixture_multiplier(fdr_for_team, e["element_type"])
        availability_mult = _availability_multiplier(e)
        wc_minutes = wc_minutes_by_id.get(pid, 0)
        fatigue_mult = _world_cup_fatigue_multiplier(wc_minutes, from_event)
        lineup_status = lineup_status_by_id.get(pid)
        if lineup_status is None and lineup_data:
            # lineup_data is active but this player's club wasn't covered/
            # matched on the page at all - riskier than a confirmed start,
            # but not as risky as being explicitly left out of a known XI.
            lineup_status = "unknown"
        lineup_mult = _LINEUP_MULTIPLIERS.get(lineup_status, 1.0)
        is_backup_gk = e["element_type"] == 1 and pid not in primary_gk_ids
        depth_mult = BACKUP_GOALKEEPER_MULT if is_backup_gk else 1.0
        score = base_scores.get(pid, 0.0) * fixture_mult * availability_mult * fatigue_mult * lineup_mult * depth_mult
        price = e["now_cost"] / 10.0
        backfill = backfilled_stats.get(pid)
        players.append({
            "id": pid,
            "web_name": e["web_name"],
            "full_name": f"{e['first_name']} {e['second_name']}",
            "team_id": e["team"],
            "team": teams_by_id[e["team"]]["name"],
            "position": POSITIONS[e["element_type"]],
            "position_id": e["element_type"],
            "price": price,
            "status": e["status"],
            "chance_of_playing_next_round": e.get("chance_of_playing_next_round"),
            "points_per_game_last_season": (backfill or {}).get("points_per_game", float(e["points_per_game"] or 0)),
            "total_points_last_season": e["total_points"],
            "xgi_per_90": (backfill or {}).get(
                "expected_goal_involvements_per_90", float(e["expected_goal_involvements_per_90"] or 0)
            ),
            "minutes_last_season": (backfill or {}).get("minutes", e["minutes"]),
            "upcoming_fdr": fdr_for_team,
            "preseason_fraction": preseason_fractions.get(pid),
            "world_cup_minutes": wc_minutes,
            "predicted_lineup_status": lineup_status,
            "stats_backfilled": backfill is not None,
            "is_backup_goalkeeper": is_backup_gk,
            "score": round(score, 2),
            "value": round(score / price, 3) if price else 0.0,
        })

    players.sort(key=lambda p: -p["score"])
    return players
