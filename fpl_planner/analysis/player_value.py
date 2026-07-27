from fpl_planner.analysis import player_match
from fpl_planner.analysis.fdr import build_team_strength, fixture_ratings, upcoming_team_fdr

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Status codes FPL uses on elements: a=available, d=doubtful, i=injured,
# s=suspended, u=unavailable (left club/not in squad), n=not available (loan etc).
_UNAVAILABLE_STATUSES = {"u", "n", "s"}

# World Cup fatigue only matters for the first few gameweeks - by GW6 a
# player's had a normal preseason-length turnaround regardless.
_FATIGUE_WINDOW_GWS = 5


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
            totals[candidate["id"]] = totals.get(candidate["id"], 0) + (entry.get("minutes_estimate") or 0)
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
        minutes[candidate["id"]] = max(minutes.get(candidate["id"], 0), entry.get("minutes_estimate") or 0)
    return minutes


def build_player_table(bootstrap, preseason_fractions=None):
    """Merge FPL per-player stats with custom fixture difficulty into a single
    scored table. Uses last-season underlying stats (points_per_game, xGI/90,
    ICT, minutes) since current-season form doesn't exist yet pre-GW1; the
    fixture multiplier is the only forward-looking adjustment. When
    preseason_fractions has an entry for a player, it's blended into the
    minutes component as a more current "nailed on" signal.
    """
    preseason_fractions = preseason_fractions or {}
    elements = bootstrap["elements"]

    by_position = {}
    for e in elements:
        by_position.setdefault(e["element_type"], []).append(e)

    base_scores = {}
    for pos, players in by_position.items():
        ppg = _percentile_ranks({p["id"]: float(p["points_per_game"] or 0) for p in players})
        xgi90 = _percentile_ranks({p["id"]: float(p["expected_goal_involvements_per_90"] or 0) for p in players})
        ict = _percentile_ranks({p["id"]: float(p["ict_index"] or 0) for p in players})
        minutes_pct = _percentile_ranks({p["id"]: float(p["minutes"] or 0) for p in players})
        for p in players:
            pid = p["id"]
            if pid in preseason_fractions:
                minutes_component = 0.4 * minutes_pct[pid] + 0.6 * preseason_fractions[pid]
            else:
                minutes_component = minutes_pct[pid]
            base_scores[pid] = (
                0.45 * ppg[pid]
                + 0.25 * xgi90[pid]
                + 0.15 * ict[pid]
                + 0.15 * minutes_component
            ) * 100

    return base_scores


def score_players(bootstrap, fixtures, understat_teams, num_gameweeks=5, from_event=1,
                   preseason_data=None, world_cup_data=None):
    """Full pipeline: team strength -> fixture ratings -> upcoming FDR ->
    per-player composite score/value. Returns a list of player dicts sorted
    by score descending. `preseason_data`/`world_cup_data` are optional -
    both fall back to no adjustment when not supplied (e.g. no ANTHROPIC_API_KEY
    configured for the LLM-assisted fetch that produces them).
    """
    strength = build_team_strength(bootstrap, understat_teams)
    ratings = fixture_ratings(fixtures, strength)
    team_fdr = upcoming_team_fdr(ratings, num_gameweeks=num_gameweeks, from_event=from_event)

    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    preseason_fractions = _preseason_fractions(bootstrap["elements"], teams_by_id, preseason_data)
    wc_minutes_by_id = _world_cup_minutes_by_player(bootstrap["elements"], world_cup_data)

    base_scores = build_player_table(bootstrap, preseason_fractions)

    players = []
    for e in bootstrap["elements"]:
        pid = e["id"]
        fdr_for_team = team_fdr.get(e["team"])
        fixture_mult = _fixture_multiplier(fdr_for_team, e["element_type"])
        availability_mult = _availability_multiplier(e)
        wc_minutes = wc_minutes_by_id.get(pid, 0)
        fatigue_mult = _world_cup_fatigue_multiplier(wc_minutes, from_event)
        score = base_scores.get(pid, 0.0) * fixture_mult * availability_mult * fatigue_mult
        price = e["now_cost"] / 10.0
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
            "points_per_game_last_season": float(e["points_per_game"] or 0),
            "total_points_last_season": e["total_points"],
            "xgi_per_90": float(e["expected_goal_involvements_per_90"] or 0),
            "minutes_last_season": e["minutes"],
            "upcoming_fdr": fdr_for_team,
            "preseason_fraction": preseason_fractions.get(pid),
            "world_cup_minutes": wc_minutes,
            "score": round(score, 2),
            "value": round(score / price, 3) if price else 0.0,
        })

    players.sort(key=lambda p: -p["score"])
    return players
