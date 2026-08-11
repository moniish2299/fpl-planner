import pulp

SQUAD_COUNTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
SQUAD_DISPLAY_ORDER = {"GKP": 4, "DEF": 3, "MID": 2, "FWD": 1}
STARTING_XI_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
MAX_PER_REAL_TEAM = 3
BENCH_WEIGHT = 0.1


def select_starting_xi(squad, score_of):
    """Pick the 11 of `squad` that maximize sum(score_of(p)) within FPL's
    starting-XI position bounds - a small enough problem (15 players) that
    solving it separately from the full squad-selection LP is cheap, and
    lets the starting XI be optimized against a different score (GW1-
    specific, or any single gameweek - see analysis/horizon.py) than
    whatever picked the 15-man squad in the first place."""
    prob = pulp.LpProblem("fpl_starting_xi", pulp.LpMaximize)
    xi_vars = {p["id"]: pulp.LpVariable(f"xi_{p['id']}", cat="Binary") for p in squad}

    prob += pulp.lpSum(score_of(p) * xi_vars[p["id"]] for p in squad)
    prob += pulp.lpSum(xi_vars.values()) == 11
    for position, (lo, hi) in STARTING_XI_BOUNDS.items():
        count = pulp.lpSum(xi_vars[p["id"]] for p in squad if p["position"] == position)
        prob += count >= lo
        prob += count <= hi

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    starting_ids = {pid for pid, var in xi_vars.items() if var.value() == 1}
    starting_xi = [p for p in squad if p["id"] in starting_ids]
    bench = [p for p in squad if p["id"] not in starting_ids]
    return starting_xi, bench


def build_squad(players, budget=100.0, max_per_team=MAX_PER_REAL_TEAM, excluded_ids=None,
                 excluded_squads=None, gw1_scores=None, must_include_ids=None):
    """Solve for the 15-man squad that maximizes score under FPL's
    budget/position/team constraints.

    `players` is the list of dicts from player_value.score_players() - its
    `score` field (typically averaged over a multi-gameweek horizon) drives
    which 15 players get drafted, since that's what a squad should be built
    around. `gw1_scores`, if given, is a separate {player_id: score} map
    used only to pick the starting XI/bench split and captain/vice within
    that squad - a player worth drafting for the next several GWs isn't
    necessarily who you'd start or captain in GW1 itself, so this keeps
    those two decisions on separate scores. `excluded_squads` is a list of
    id-sets; each solve is barred from reproducing one exactly (see
    `build_top_squads`), yielding distinct near-optimal squads in ranked
    order rather than the same one every time. `must_include_ids`, if
    given, forces those player ids into every returned squad - the
    optimizer still picks the other 15-minus-N players and the starting
    XI/captain freely, so a required player isn't guaranteed to start,
    just to be on the 15.

    Returns None if no feasible squad remains (e.g. the required players
    and budget/position/team constraints can't all be satisfied at once).
    """
    excluded_ids = excluded_ids or set()
    excluded_squads = excluded_squads or []
    must_include_ids = must_include_ids or set()
    pool = [p for p in players if p["id"] not in excluded_ids and p["status"] != "u"]

    prob = pulp.LpProblem("fpl_draft", pulp.LpMaximize)
    squad_vars = {p["id"]: pulp.LpVariable(f"squad_{p['id']}", cat="Binary") for p in pool}
    xi_vars = {p["id"]: pulp.LpVariable(f"xi_{p['id']}", cat="Binary") for p in pool}

    prob += pulp.lpSum(
        p["score"] * xi_vars[p["id"]] + BENCH_WEIGHT * p["score"] * (squad_vars[p["id"]] - xi_vars[p["id"]])
        for p in pool
    )

    prob += pulp.lpSum(squad_vars.values()) == 15
    prob += pulp.lpSum(p["price"] * squad_vars[p["id"]] for p in pool) <= budget
    prob += pulp.lpSum(xi_vars.values()) == 11

    for p in pool:
        prob += xi_vars[p["id"]] <= squad_vars[p["id"]]

    for position, count in SQUAD_COUNTS.items():
        prob += pulp.lpSum(squad_vars[p["id"]] for p in pool if p["position"] == position) == count

    for position, (lo, hi) in STARTING_XI_BOUNDS.items():
        xi_count = pulp.lpSum(xi_vars[p["id"]] for p in pool if p["position"] == position)
        prob += xi_count >= lo
        prob += xi_count <= hi

    team_ids = {p["team_id"] for p in pool}
    for team_id in team_ids:
        prob += pulp.lpSum(squad_vars[p["id"]] for p in pool if p["team_id"] == team_id) <= max_per_team

    for combo in excluded_squads:
        combo_in_pool = [pid for pid in combo if pid in squad_vars]
        prob += pulp.lpSum(squad_vars[pid] for pid in combo_in_pool) <= len(combo) - 1

    for pid in must_include_ids:
        if pid in squad_vars:
            prob += squad_vars[pid] == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if prob.status != pulp.LpStatusOptimal:
        return None

    by_id = {p["id"]: p for p in pool}
    squad = [by_id[pid] for pid, var in squad_vars.items() if var.value() == 1]

    gw1_scores = gw1_scores or {}

    def gw1_score(p):
        return gw1_scores.get(p["id"], p["score"])

    if gw1_scores:
        starting_xi, bench = select_starting_xi(squad, gw1_score)
    else:
        starting_ids = {pid for pid, var in xi_vars.items() if var.value() == 1}
        starting_xi = [p for p in squad if p["id"] in starting_ids]
        bench = [p for p in squad if p["id"] not in starting_ids]

    for p in squad:
        p["gw1_score"] = gw1_score(p)

    starting_xi.sort(key=lambda p: -gw1_score(p))
    bench.sort(key=lambda p: -gw1_score(p))
    squad.sort(key=lambda p: (-SQUAD_DISPLAY_ORDER[p["position"]], -gw1_score(p)))

    captain, vice_captain = starting_xi[0], starting_xi[1]

    return {
        "squad": squad,
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "total_cost": round(sum(p["price"] for p in squad), 1),
        "budget_remaining": round(budget - sum(p["price"] for p in squad), 1),
        "objective_score": round(pulp.value(prob.objective), 1),
    }


def build_top_squads(players, budget=100.0, count=5, max_per_team=MAX_PER_REAL_TEAM, gw1_scores=None,
                      must_include_ids=None):
    """Returns up to `count` distinct squads in descending-score order, using
    the standard solve/exclude-that-exact-combo/resolve loop: each solve is
    barred from reproducing any earlier squad exactly, so this is the top-N
    distinct optimal squads rather than N arbitrary ones. Stops early if
    fewer than `count` feasible distinct squads exist."""
    results = []
    excluded_squads = []
    for _ in range(count):
        result = build_squad(
            players, budget=budget, max_per_team=max_per_team,
            excluded_squads=excluded_squads, gw1_scores=gw1_scores, must_include_ids=must_include_ids,
        )
        if result is None:
            break
        results.append(result)
        excluded_squads.append({p["id"] for p in result["squad"]})
    return results
