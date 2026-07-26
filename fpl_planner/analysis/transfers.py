from fpl_planner.analysis.draft import MAX_PER_REAL_TEAM

TRANSFER_COST = 4


def suggest_transfers(players, current_squad_ids, bank, free_transfers=1, max_suggestions=5):
    """For each player in the current squad, find the single best replacement
    (same position, affordable within squad value + bank, respecting the
    max-3-per-team rule) and rank all such swaps by score gain.

    A swap beyond `free_transfers` costs TRANSFER_COST (4pts); gain_after_hit
    reflects that so a marginal swap that isn't worth a hit sorts low.
    """
    by_id = {p["id"]: p for p in players}
    squad = [by_id[pid] for pid in current_squad_ids if pid in by_id]
    squad_ids = {p["id"] for p in squad}
    team_counts = {}
    for p in squad:
        team_counts[p["team_id"]] = team_counts.get(p["team_id"], 0) + 1
    total_budget = sum(p["price"] for p in squad) + bank

    suggestions = []
    for outgoing in squad:
        remaining_value = total_budget - sum(p["price"] for p in squad if p["id"] != outgoing["id"])
        best_candidate = None
        for candidate in players:
            if candidate["id"] in squad_ids:
                continue
            if candidate["position"] != outgoing["position"]:
                continue
            if candidate["price"] > remaining_value:
                continue
            team_count = team_counts.get(candidate["team_id"], 0)
            if candidate["team_id"] != outgoing["team_id"] and team_count >= MAX_PER_REAL_TEAM:
                continue
            if best_candidate is None or candidate["score"] > best_candidate["score"]:
                best_candidate = candidate

        if best_candidate and best_candidate["score"] > outgoing["score"]:
            gain = round(best_candidate["score"] - outgoing["score"], 2)
            suggestions.append({
                "out": outgoing,
                "in": best_candidate,
                "gain": gain,
                "gain_after_hit": round(gain - TRANSFER_COST, 2),
                "cost_delta": round(best_candidate["price"] - outgoing["price"], 1),
            })

    suggestions.sort(key=lambda s: -s["gain"])

    for i, s in enumerate(suggestions):
        s["within_free_transfers"] = i < free_transfers
        s["worth_a_hit"] = s["gain_after_hit"] > 0

    return suggestions[:max_suggestions]
