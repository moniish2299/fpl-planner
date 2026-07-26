def gameweek_fixture_counts(fixtures, gameweek):
    counts = {}
    for f in fixtures:
        if f.get("event") != gameweek:
            continue
        counts[f["team_h"]] = counts.get(f["team_h"], 0) + 1
        counts[f["team_a"]] = counts.get(f["team_a"], 0) + 1
    return counts


def recommend_captain(players, squad_ids, fixtures, target_gameweek):
    """Rank squad players for the captaincy of a single target gameweek.
    `players` should be scored for that one gameweek (score_players with
    num_gameweeks=1, from_event=target_gameweek) so the fixture adjustment is
    specific to it. Players whose team has two fixtures that gameweek (a
    double gameweek) get their score doubled; players with no fixture (a
    blank gameweek for their team) are excluded from consideration.
    """
    fixture_count = gameweek_fixture_counts(fixtures, target_gameweek)
    by_id = {p["id"]: p for p in players}

    candidates = []
    for pid in squad_ids:
        p = by_id.get(pid)
        if p is None:
            continue
        n_fixtures = fixture_count.get(p["team_id"], 0)
        if n_fixtures == 0:
            continue
        candidates.append({
            **p,
            "gameweek_fixtures": n_fixtures,
            "adjusted_score": round(p["score"] * n_fixtures, 2),
        })

    candidates.sort(key=lambda c: -c["adjusted_score"])

    return {
        "captain": candidates[0] if candidates else None,
        "vice_captain": candidates[1] if len(candidates) > 1 else None,
        "candidates": candidates[:5],
    }
