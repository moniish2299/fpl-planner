import argparse
import sys

from fpl_planner.analysis import captain as captain_module
from fpl_planner.analysis import chips as chips_module
from fpl_planner.analysis import draft as draft_module
from fpl_planner.analysis import fdr as fdr_module
from fpl_planner.analysis import player_value
from fpl_planner.analysis import transfers as transfers_module
from fpl_planner.config import LLM_PROVIDER, get_llm_api_key, get_team_id, get_understat_season, get_world_cup_year
from fpl_planner.fetch import fpl_api, preseason, understat, worldcup
from fpl_planner.storage import load_json, save_json


def fetch(team_id=None, understat_season=None):
    print("Fetching bootstrap-static (players, teams, gameweeks)...")
    bootstrap = fpl_api.get_bootstrap()
    save_json("bootstrap", bootstrap)
    print(f"  saved {len(bootstrap.get('elements', []))} players, "
          f"{len(bootstrap.get('teams', []))} teams")

    print("Fetching fixtures...")
    fixtures = fpl_api.get_fixtures()
    save_json("fixtures", fixtures)
    print(f"  saved {len(fixtures)} fixtures")

    season = understat_season or get_understat_season()
    print(f"Fetching Understat data ({season})...")
    try:
        league_data = understat.get_league_data(season)
        save_json("understat", league_data["players"])
        save_json("understat_teams", league_data["teams"])
        print(f"  saved {len(league_data['players'])} players, {len(league_data['teams'])} teams")
    except Exception as exc:
        print(f"  skipped Understat fetch: {exc}", file=sys.stderr)

    if get_llm_api_key():
        wc_year = get_world_cup_year()
        print(f"Fetching World Cup fatigue data ({wc_year}, LLM-assisted via {LLM_PROVIDER})...")
        try:
            wc_data = worldcup.get_world_cup_minutes(wc_year)
            save_json("worldcup", wc_data)
            print(f"  saved minutes for {len(wc_data)} World Cup players")
        except Exception as exc:
            print(f"  skipped World Cup fetch: {exc}", file=sys.stderr)

        print(f"Fetching preseason friendly lineups (LLM-assisted, {len(preseason.BBC_SLUGS)} clubs)...")
        preseason_data = {}
        for club_name in preseason.BBC_SLUGS:
            try:
                appearances, matches_covered = preseason.get_club_preseason_appearances(club_name)
                preseason_data[club_name] = {"appearances": appearances, "matches_covered": matches_covered}
            except Exception as exc:
                print(f"  skipped {club_name}: {exc}", file=sys.stderr)
        save_json("preseason", preseason_data)
        covered = sum(1 for d in preseason_data.values() if d.get("matches_covered"))
        print(f"  saved preseason data for {covered}/{len(preseason.BBC_SLUGS)} clubs")
    else:
        print(f"No API key set for LLM provider '{LLM_PROVIDER}' (set GEMINI_API_KEY, ANTHROPIC_API_KEY if "
              "using FPL_PLANNER_LLM_PROVIDER=anthropic, or FPL_PLANNER_LLM_API_KEY), skipping World Cup "
              "fatigue + preseason lineup data (these extract structured data out of prose match reports "
              "via an LLM call).")

    team_id = team_id or get_team_id()
    if team_id:
        print(f"Fetching your team (id={team_id})...")
        entry = fpl_api.get_entry(team_id)
        save_json(f"entry_{team_id}", entry)

        history = fpl_api.get_entry_history(team_id)
        save_json(f"entry_{team_id}_history", history)

        target_gw = next(
            (e["id"] for e in bootstrap.get("events", []) if e.get("is_current") or e.get("is_next")),
            None,
        )
        picks_saved = False
        if target_gw:
            try:
                picks = fpl_api.get_entry_picks(team_id, target_gw)
                save_json(f"entry_{team_id}_picks", picks)
                picks_saved = True
                print(f"  saved entry, history, and picks for gameweek {target_gw}")
            except Exception:
                pass
        if not picks_saved:
            print("  saved entry and history (no squad picks found yet - use the draft planner)")
    else:
        print("No FPL_TEAM_ID set, skipping your team's data. "
              "Set the FPL_TEAM_ID env var or pass --team-id to fetch it.")


def _load_optional_json(name):
    try:
        return load_json(name)
    except FileNotFoundError:
        return None


def _load_cached_data():
    try:
        bootstrap = load_json("bootstrap")
        fixtures = load_json("fixtures")
        understat_teams = load_json("understat_teams")
    except FileNotFoundError:
        print("No cached data found. Run `python -m fpl_planner.cli fetch` first.", file=sys.stderr)
        sys.exit(1)
    return bootstrap, fixtures, understat_teams


def _load_signal_data(args=None):
    """World Cup fatigue / preseason data are optional (need an LLM API key
    at fetch time) - score_players() treats missing data as no adjustment.
    Either can also be force-disabled per-command via --no-world-cup/
    --no-preseason even when the cached data is present."""
    preseason_data = _load_optional_json("preseason")
    world_cup_data = _load_optional_json("worldcup")
    if args and getattr(args, "no_preseason", False):
        preseason_data = None
    if args and getattr(args, "no_world_cup", False):
        world_cup_data = None
    return preseason_data, world_cup_data


def _current_or_next_event(bootstrap):
    return next(
        (e["id"] for e in bootstrap.get("events", []) if e.get("is_current") or e.get("is_next")),
        1,
    )


def _load_squad(team_id):
    try:
        picks = load_json(f"entry_{team_id}_picks")
    except FileNotFoundError:
        print(
            f"No squad picks found for team {team_id}. Run `fetch --team-id {team_id}` after you've "
            "saved a squad, or use `draft` to build one first.",
            file=sys.stderr,
        )
        sys.exit(1)
    squad_ids = [p["element"] for p in picks["picks"]]
    bank = picks["entry_history"]["bank"] / 10.0
    return squad_ids, bank


def cmd_fdr(args):
    bootstrap, fixtures, understat_teams = _load_cached_data()
    strength = fdr_module.build_team_strength(bootstrap, understat_teams)
    if strength["proxied_teams"]:
        print(f"Promoted teams using a relegated team's stats as a proxy: {strength['proxied_teams']}")
    if strength["unmatched_teams"]:
        print(f"Could not match (no prior-season proxy available): {strength['unmatched_teams']}")

    ratings = fdr_module.fixture_ratings(fixtures, strength)
    from_event = args.from_event or _current_or_next_event(bootstrap)
    upcoming = fdr_module.upcoming_team_fdr(ratings, num_gameweeks=args.gameweeks, from_event=from_event)
    team_names = {t["id"]: t["name"] for t in bootstrap["teams"]}

    print(f"\nCustom FDR, GW{from_event}-{from_event + args.gameweeks - 1} "
          f"(1=easiest, 5=hardest; attack = scoring difficulty, defense = clean sheet difficulty):\n")
    rows = sorted(upcoming.items(), key=lambda kv: kv[1]["attack"])
    for tid, v in rows:
        print(f"  {team_names.get(tid, tid):16s} attack={v['attack']:.1f}  defense={v['defense']:.1f}  "
              f"({v['fixtures']} fixtures)")


def _signal_flags(p):
    flags = []
    if p.get("world_cup_minutes"):
        flags.append(f"WC:{p['world_cup_minutes']:.0f}min")
    if p.get("preseason_fraction") is not None:
        flags.append(f"preseason:{p['preseason_fraction']*100:.0f}%")
    return f" [{', '.join(flags)}]" if flags else ""


def cmd_draft(args):
    bootstrap, fixtures, understat_teams = _load_cached_data()
    preseason_data, world_cup_data = _load_signal_data(args)
    from_event = args.from_event or _current_or_next_event(bootstrap)
    players = player_value.score_players(
        bootstrap, fixtures, understat_teams, num_gameweeks=args.gameweeks, from_event=from_event,
        preseason_data=preseason_data, world_cup_data=world_cup_data,
    )
    # Squad selection uses the multi-GW score above (what's worth drafting
    # over the horizon), but starting XI/bench and captain/vice should
    # reflect GW1 specifically, not an average across the horizon - a GW1
    # score, single gameweek from the same starting point.
    gw1_players = player_value.score_players(
        bootstrap, fixtures, understat_teams, num_gameweeks=1, from_event=from_event,
        preseason_data=preseason_data, world_cup_data=world_cup_data,
    )
    gw1_scores = {p["id"]: p["score"] for p in gw1_players}

    results = draft_module.build_top_squads(players, budget=args.budget, count=5, gw1_scores=gw1_scores)
    if not results:
        print("No feasible squad found for that budget.", file=sys.stderr)
        sys.exit(1)

    for i, result in enumerate(results, start=1):
        print(f"\n=== Option {i}/{len(results)} (budget £{args.budget}m, using next {args.gameweeks} GWs "
              f"from GW{from_event}, starting XI/captain for GW{from_event}) ===")
        print(f"Total cost: £{result['total_cost']}m, remaining: £{result['budget_remaining']}m\n")
        for p in result["squad"]:
            tag = " (C)" if p["id"] == result["captain"]["id"] else (" (V)" if p["id"] == result["vice_captain"]["id"] else "")
            bench = "" if p in result["starting_xi"] else " [BENCH]"
            print(f"  {p['position']:4s} {p['web_name']:16s} {p['team']:15s} £{p['price']:.1f}  "
                  f"score={p['score']:.1f} gw1={p['gw1_score']:.1f}{tag}{bench}{_signal_flags(p)}")


def cmd_transfers(args):
    bootstrap, fixtures, understat_teams = _load_cached_data()
    preseason_data, world_cup_data = _load_signal_data(args)
    team_id = args.team_id or get_team_id()
    if not team_id:
        print("Provide --team-id or set FPL_TEAM_ID.", file=sys.stderr)
        sys.exit(1)
    squad_ids, bank = _load_squad(team_id)

    from_event = args.from_event or _current_or_next_event(bootstrap)
    players = player_value.score_players(
        bootstrap, fixtures, understat_teams, num_gameweeks=args.gameweeks, from_event=from_event,
        preseason_data=preseason_data, world_cup_data=world_cup_data,
    )
    suggestions = transfers_module.suggest_transfers(
        players, squad_ids, bank, free_transfers=args.free_transfers, max_suggestions=args.max_suggestions
    )

    if not suggestions:
        print("No improving transfers found - your squad already looks strong for the upcoming fixtures.")
        return

    print(f"\nTransfer suggestions (next {args.gameweeks} GWs from GW{from_event}, bank £{bank}m):\n")
    for s in suggestions:
        hit_note = "FREE" if s["within_free_transfers"] else ("worth a hit" if s["worth_a_hit"] else "not worth a hit")
        print(f"  OUT {s['out']['web_name']:16s} ({s['out']['score']:.1f}) -> "
              f"IN {s['in']['web_name']:16s} ({s['in']['score']:.1f})  "
              f"gain={s['gain']:+.1f}  cost_delta=£{s['cost_delta']:+.1f}m  [{hit_note}]{_signal_flags(s['in'])}")


def cmd_captain(args):
    bootstrap, fixtures, understat_teams = _load_cached_data()
    preseason_data, world_cup_data = _load_signal_data(args)
    team_id = args.team_id or get_team_id()
    if not team_id:
        print("Provide --team-id or set FPL_TEAM_ID.", file=sys.stderr)
        sys.exit(1)
    squad_ids, _ = _load_squad(team_id)

    target_gw = args.gameweek or _current_or_next_event(bootstrap)
    players = player_value.score_players(
        bootstrap, fixtures, understat_teams, num_gameweeks=1, from_event=target_gw,
        preseason_data=preseason_data, world_cup_data=world_cup_data,
    )
    result = captain_module.recommend_captain(players, squad_ids, fixtures, target_gw)

    print(f"\nCaptain recommendation for GW{target_gw}:\n")
    if not result["candidates"]:
        print("  No squad players have a fixture this gameweek (blank gameweek).")
        return
    for c in result["candidates"]:
        tag = " (C)" if result["captain"] and c["id"] == result["captain"]["id"] else (
            " (V)" if result["vice_captain"] and c["id"] == result["vice_captain"]["id"] else "")
        dgw = " [DGW]" if c["gameweek_fixtures"] > 1 else ""
        print(f"  {c['web_name']:16s} {c['team']:15s} score={c['score']:.1f}  "
              f"adjusted={c['adjusted_score']:.1f}{dgw}{tag}{_signal_flags(c)}")


def cmd_chips(args):
    bootstrap, fixtures, understat_teams = _load_cached_data()
    from_event = args.from_event or _current_or_next_event(bootstrap)

    squad_team_ids = None
    team_id = args.team_id or get_team_id()
    if team_id:
        try:
            squad_ids, _ = _load_squad(team_id)
            by_id = {p["id"]: p for p in player_value.score_players(bootstrap, fixtures, understat_teams)}
            squad_team_ids = {by_id[pid]["team_id"] for pid in squad_ids if pid in by_id}
        except SystemExit:
            squad_team_ids = None

    recommendations = chips_module.recommend_chips(fixtures, current_event=from_event, squad_team_ids=squad_team_ids)
    print(f"\nChip recommendations from GW{from_event}:\n")
    for r in recommendations:
        gw = f"GW{r['gameweek']}" if r["gameweek"] else "no specific gameweek yet"
        print(f"  [{r['chip']}] {gw}\n    {r['reason']}\n")


def main():
    parser = argparse.ArgumentParser(prog="fpl_planner", description="FPL data planning tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and cache FPL + Understat data")
    fetch_parser.add_argument("--team-id", help="Your FPL team/entry ID (overrides FPL_TEAM_ID env var)")
    fetch_parser.add_argument("--understat-season", help="Understat season, e.g. 2025 for 2025-26")

    fdr_parser = subparsers.add_parser("fdr", help="Show custom fixture difficulty ratings")
    fdr_parser.add_argument("--gameweeks", type=int, default=5, help="Number of upcoming gameweeks to average over")
    fdr_parser.add_argument("--from-event", type=int, help="Gameweek to start from (default: current/next)")

    draft_parser = subparsers.add_parser("draft", help="Build a pre-GW1 (or any-time) squad from scratch")
    draft_parser.add_argument("--budget", type=float, default=100.0, help="Total squad budget in £m")
    draft_parser.add_argument("--gameweeks", type=int, default=5, help="Fixture horizon to optimize for")
    draft_parser.add_argument("--from-event", type=int, help="Gameweek to start the fixture horizon from")
    draft_parser.add_argument("--no-world-cup", action="store_true", help="Ignore the World Cup fatigue signal even if cached")
    draft_parser.add_argument("--no-preseason", action="store_true", help="Ignore the preseason minutes signal even if cached")

    transfers_parser = subparsers.add_parser("transfers", help="Suggest transfers for your saved squad")
    transfers_parser.add_argument("--team-id", help="Your FPL team/entry ID (overrides FPL_TEAM_ID env var)")
    transfers_parser.add_argument("--gameweeks", type=int, default=5, help="Fixture horizon to optimize for")
    transfers_parser.add_argument("--from-event", type=int, help="Gameweek to start the fixture horizon from")
    transfers_parser.add_argument("--free-transfers", type=int, default=1, help="Free transfers you have available")
    transfers_parser.add_argument("--max-suggestions", type=int, default=5)
    transfers_parser.add_argument("--no-world-cup", action="store_true", help="Ignore the World Cup fatigue signal even if cached")
    transfers_parser.add_argument("--no-preseason", action="store_true", help="Ignore the preseason minutes signal even if cached")

    captain_parser = subparsers.add_parser("captain", help="Recommend captain/vice-captain for your saved squad")
    captain_parser.add_argument("--team-id", help="Your FPL team/entry ID (overrides FPL_TEAM_ID env var)")
    captain_parser.add_argument("--gameweek", type=int, help="Gameweek to recommend for (default: current/next)")
    captain_parser.add_argument("--no-world-cup", action="store_true", help="Ignore the World Cup fatigue signal even if cached")
    captain_parser.add_argument("--no-preseason", action="store_true", help="Ignore the preseason minutes signal even if cached")

    chips_parser = subparsers.add_parser("chips", help="Recommend chip timing (Wildcard/Bench Boost/Triple Captain/Free Hit)")
    chips_parser.add_argument("--team-id", help="Your FPL team/entry ID (overrides FPL_TEAM_ID env var)")
    chips_parser.add_argument("--from-event", type=int, help="Gameweek to start looking from (default: current/next)")

    args = parser.parse_args()

    commands = {
        "fetch": lambda: fetch(team_id=args.team_id, understat_season=args.understat_season),
        "fdr": lambda: cmd_fdr(args),
        "draft": lambda: cmd_draft(args),
        "transfers": lambda: cmd_transfers(args),
        "captain": lambda: cmd_captain(args),
        "chips": lambda: cmd_chips(args),
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
