from fpl_planner.analysis import captain as captain_module
from fpl_planner.analysis import draft as draft_module
from fpl_planner.analysis import player_value
from fpl_planner.analysis import transfers as transfers_module

FREE_TRANSFERS_PER_GW = 1
MAX_SAVED_FREE_TRANSFERS = 5


def _adjusted_score(p, fixture_count):
    """Zero out blank-gameweek players, double up double-gameweek ones - the
    same fixture-count adjustment recommend_captain() applies to captaincy,
    extended here to the starting XI/bench decision itself, so a blank/
    double gameweek can rotate the XI even with no transfer at all."""
    return p["score"] * fixture_count.get(p["team_id"], 0)


def plan_horizon(initial_squad_ids, bank, bootstrap, fixtures, understat_teams, gameweeks, from_event,
                  preseason_data=None, world_cup_data=None, lineup_data=None):
    """Week-by-week plan across the drafted squad's fixture horizon: which
    single transfer (if any) is worth making that week, and which of the
    15 squad members should start vs sit given that week's fixtures - i.e.
    bench rotation, not just a static GW1 starting XI.

    Starts from `initial_squad_ids` (the squad build_squad()/build_top_squads()
    picked) and `bank` (its budget_remaining), then simulates forward one
    gameweek at a time:
      - GW1 (the draft itself) has no transfer decision - just that week's
        starting XI/bench/captain.
      - From GW2 on, the single best available transfer (if any exists) is
        taken when it's free, or when its point gain over the *remaining*
        horizon outweighs the 4-point hit. Free transfers accumulate by 1
        each week one isn't used, capped at MAX_SAVED_FREE_TRANSFERS,
        approximating FPL's saved-transfer rule.
      - Each week's starting XI/bench/captain/vice-captain is re-picked from
        whatever the squad looks like that week, using that week's fixture-
        adjusted score, so blank/double gameweeks can change who starts or
        captains independently of any transfer.
      - `lineup_data` (RotoWire predicted lineups), if given, only ever
        applies to gameweek 1 specifically - predicted lineups aren't
        meaningful more than a few days out, so later weeks in the horizon
        never see it regardless of `from_event`.

    Only ever considers one transfer per gameweek - it doesn't model taking
    two hits in the same week for a double swap.

    Returns a list of per-gameweek dicts: {"gameweek", "transfer" (None or
    {"out", "in", "gain", "hit"}), "starting_xi", "bench", "captain",
    "vice_captain", "rotation_in", "rotation_out", "free_transfers_after"}.
    """
    squad_ids = set(initial_squad_ids)
    free_transfers = 0
    previous_xi_ids = None
    weekly_plans = []

    for i in range(gameweeks):
        gw = from_event + i
        remaining_gws = gameweeks - i
        pool_for_transfers = player_value.score_players(
            bootstrap, fixtures, understat_teams, num_gameweeks=remaining_gws, from_event=gw,
            preseason_data=preseason_data, world_cup_data=world_cup_data,
        )
        gw_scores = player_value.score_players(
            bootstrap, fixtures, understat_teams, num_gameweeks=1, from_event=gw,
            preseason_data=preseason_data, world_cup_data=world_cup_data,
            lineup_data=lineup_data if gw == 1 else None,
        )

        transfer_made = None
        if i > 0:
            suggestions = transfers_module.suggest_transfers(
                pool_for_transfers, squad_ids, bank, free_transfers=free_transfers, max_suggestions=1,
            )
            if suggestions and (suggestions[0]["within_free_transfers"] or suggestions[0]["worth_a_hit"]):
                s = suggestions[0]
                squad_ids.discard(s["out"]["id"])
                squad_ids.add(s["in"]["id"])
                bank = round(bank - s["cost_delta"], 1)
                if s["within_free_transfers"]:
                    hit = 0
                    free_transfers -= 1
                else:
                    hit = transfers_module.TRANSFER_COST
                transfer_made = {"out": s["out"], "in": s["in"], "gain": s["gain"], "hit": hit}

        by_id = {p["id"]: p for p in gw_scores}
        current_squad = [by_id[pid] for pid in squad_ids if pid in by_id]

        fixture_count = captain_module.gameweek_fixture_counts(fixtures, gw)
        starting_xi, bench = draft_module.select_starting_xi(
            current_squad, lambda p: _adjusted_score(p, fixture_count)
        )
        starting_xi.sort(key=lambda p: -_adjusted_score(p, fixture_count))
        bench.sort(key=lambda p: -_adjusted_score(p, fixture_count))

        captain_result = captain_module.recommend_captain(gw_scores, squad_ids, fixtures, gw)

        xi_ids = {p["id"] for p in starting_xi}
        rotation_in, rotation_out = [], []
        if previous_xi_ids is not None:
            transferred_ids = {transfer_made["out"]["id"], transfer_made["in"]["id"]} if transfer_made else set()
            newly_in_ids = (xi_ids - previous_xi_ids) - transferred_ids
            newly_out_ids = (previous_xi_ids - xi_ids) - transferred_ids
            rotation_in = [p for p in starting_xi if p["id"] in newly_in_ids]
            rotation_out = [p for p in bench if p["id"] in newly_out_ids]
        previous_xi_ids = xi_ids

        weekly_plans.append({
            "gameweek": gw,
            "transfer": transfer_made,
            "starting_xi": starting_xi,
            "bench": bench,
            "captain": captain_result["captain"],
            "vice_captain": captain_result["vice_captain"],
            "rotation_in": rotation_in,
            "rotation_out": rotation_out,
            "free_transfers_after": free_transfers,
        })

        free_transfers = min(MAX_SAVED_FREE_TRANSFERS, free_transfers + FREE_TRANSFERS_PER_GW)

    return weekly_plans
