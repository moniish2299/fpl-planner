from fpl_planner.analysis.captain import gameweek_fixture_counts
from fpl_planner.analysis.draft import select_starting_xi


def recommend_lineup(players, squad_ids, fixtures, target_gameweek):
    """Pick a starting XI + bench for `target_gameweek` from an already-owned
    15-man squad. `players` should be scored for that one gameweek
    (score_players with num_gameweeks=1, from_event=target_gameweek) so the
    fixture adjustment below matches it.

    Each squad player is valued at score * fixture count for that gameweek -
    the same blank/double-gameweek weighting recommend_captain uses - so a
    squad member with no fixture that week (0) naturally sorts to the bench
    behind anyone with a game, and a double-gameweek player is preferred,
    without a hard exclusion rule.
    """
    fixture_count = gameweek_fixture_counts(fixtures, target_gameweek)
    by_id = {p["id"]: p for p in players}
    squad = [by_id[pid] for pid in squad_ids if pid in by_id]

    def score_of(p):
        return p["score"] * fixture_count.get(p["team_id"], 0)

    starting_xi, bench = select_starting_xi(squad, score_of)
    starting_xi.sort(key=lambda p: -score_of(p))
    # Real FPL bench order: the spare keeper is always last (only the other
    # keeper can autosub for them), outfield subs 1-2-3 ranked by who you'd
    # bring on first.
    bench.sort(key=lambda p: (p["position"] == "GKP", -score_of(p)))

    return {"squad": squad, "starting_xi": starting_xi, "bench": bench}
