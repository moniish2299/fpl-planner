from fpl_planner.analysis.fdr import build_team_strength, fixture_ratings, upcoming_team_fdr

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Status codes FPL uses on elements: a=available, d=doubtful, i=injured,
# s=suspended, u=unavailable (left club/not in squad), n=not available (loan etc).
_UNAVAILABLE_STATUSES = {"u", "n", "s"}


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


def build_player_table(bootstrap):
    """Merge FPL per-player stats with custom fixture difficulty into a single
    scored table. Uses last-season underlying stats (points_per_game, xGI/90,
    ICT, minutes) since current-season form doesn't exist yet pre-GW1; the
    fixture multiplier is the only forward-looking adjustment.
    """
    elements = bootstrap["elements"]

    by_position = {}
    for e in elements:
        by_position.setdefault(e["element_type"], []).append(e)

    base_scores = {}
    for pos, players in by_position.items():
        ppg = _percentile_ranks({p["id"]: float(p["points_per_game"] or 0) for p in players})
        xgi90 = _percentile_ranks({p["id"]: float(p["expected_goal_involvements_per_90"] or 0) for p in players})
        ict = _percentile_ranks({p["id"]: float(p["ict_index"] or 0) for p in players})
        minutes = _percentile_ranks({p["id"]: float(p["minutes"] or 0) for p in players})
        for p in players:
            base_scores[p["id"]] = (
                0.45 * ppg[p["id"]]
                + 0.25 * xgi90[p["id"]]
                + 0.15 * ict[p["id"]]
                + 0.15 * minutes[p["id"]]
            ) * 100

    return base_scores


def score_players(bootstrap, fixtures, understat_teams, num_gameweeks=5, from_event=1):
    """Full pipeline: team strength -> fixture ratings -> upcoming FDR ->
    per-player composite score/value. Returns a list of player dicts sorted
    by score descending.
    """
    strength = build_team_strength(bootstrap, understat_teams)
    ratings = fixture_ratings(fixtures, strength)
    team_fdr = upcoming_team_fdr(ratings, num_gameweeks=num_gameweeks, from_event=from_event)

    base_scores = build_player_table(bootstrap)
    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}

    players = []
    for e in bootstrap["elements"]:
        pid = e["id"]
        fdr_for_team = team_fdr.get(e["team"])
        fixture_mult = _fixture_multiplier(fdr_for_team, e["element_type"])
        availability_mult = _availability_multiplier(e)
        score = base_scores.get(pid, 0.0) * fixture_mult * availability_mult
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
            "score": round(score, 2),
            "value": round(score / price, 3) if price else 0.0,
        })

    players.sort(key=lambda p: -p["score"])
    return players
