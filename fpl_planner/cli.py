import argparse
import sys

from fpl_planner.config import get_team_id, get_understat_season
from fpl_planner.fetch import fpl_api, understat
from fpl_planner.storage import save_json


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
    print(f"Fetching Understat player data ({season})...")
    try:
        understat_players = understat.get_league_players(season)
        save_json("understat", understat_players)
        print(f"  saved {len(understat_players)} players")
    except Exception as exc:
        print(f"  skipped Understat fetch: {exc}", file=sys.stderr)

    team_id = team_id or get_team_id()
    if team_id:
        print(f"Fetching your team (id={team_id})...")
        entry = fpl_api.get_entry(team_id)
        save_json(f"entry_{team_id}", entry)

        history = fpl_api.get_entry_history(team_id)
        save_json(f"entry_{team_id}_history", history)

        current_gw = next(
            (e["id"] for e in bootstrap.get("events", []) if e.get("is_current")),
            None,
        )
        if current_gw:
            picks = fpl_api.get_entry_picks(team_id, current_gw)
            save_json(f"entry_{team_id}_picks", picks)
            print(f"  saved entry, history, and picks for gameweek {current_gw}")
        else:
            print("  saved entry and history (no current gameweek found for picks)")
    else:
        print("No FPL_TEAM_ID set, skipping your team's data. "
              "Set the FPL_TEAM_ID env var or pass --team-id to fetch it.")


def main():
    parser = argparse.ArgumentParser(prog="fpl_planner", description="FPL data planning tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and cache FPL + Understat data")
    fetch_parser.add_argument("--team-id", help="Your FPL team/entry ID (overrides FPL_TEAM_ID env var)")
    fetch_parser.add_argument("--understat-season", help="Understat season, e.g. 2025 for 2025-26")

    args = parser.parse_args()

    if args.command == "fetch":
        fetch(team_id=args.team_id, understat_season=args.understat_season)


if __name__ == "__main__":
    main()
