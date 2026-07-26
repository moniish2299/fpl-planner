import pulp

SQUAD_COUNTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
SQUAD_DISPLAY_ORDER = {"GKP": 4, "DEF": 3, "MID": 2, "FWD": 1}
STARTING_XI_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
MAX_PER_REAL_TEAM = 3
BENCH_WEIGHT = 0.1


def build_squad(players, budget=100.0, max_per_team=MAX_PER_REAL_TEAM, excluded_ids=None):
    """Solve for the 15-man squad (and a strong starting XI within it) that
    maximizes score under FPL's budget/position/team constraints.

    `players` is the list of dicts from player_value.score_players(). Returns
    a dict with squad, starting_xi, bench, captain, vice_captain, total_cost.
    """
    excluded_ids = excluded_ids or set()
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

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if prob.status != pulp.LpStatusOptimal:
        raise RuntimeError(f"No feasible squad found (solver status: {pulp.LpStatus[prob.status]})")

    by_id = {p["id"]: p for p in pool}
    squad = [by_id[pid] for pid, var in squad_vars.items() if var.value() == 1]
    starting_ids = {pid for pid, var in xi_vars.items() if var.value() == 1}
    starting_xi = [p for p in squad if p["id"] in starting_ids]
    bench = [p for p in squad if p["id"] not in starting_ids]

    starting_xi.sort(key=lambda p: -p["score"])
    bench.sort(key=lambda p: -p["score"])
    squad.sort(key=lambda p: (-SQUAD_DISPLAY_ORDER[p["position"]], -p["score"]))

    captain, vice_captain = starting_xi[0], starting_xi[1]

    return {
        "squad": squad,
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "total_cost": round(sum(p["price"] for p in squad), 1),
        "budget_remaining": round(budget - sum(p["price"] for p in squad), 1),
    }
