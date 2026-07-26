import requests

from fpl_planner.config import FPL_BASE_URL, USER_AGENT

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _get(path):
    response = _session.get(f"{FPL_BASE_URL}/{path}", timeout=15)
    response.raise_for_status()
    return response.json()


def get_bootstrap():
    """All players, teams, positions, and gameweeks."""
    return _get("bootstrap-static/")


def get_fixtures():
    """Full season fixture list with FDR."""
    return _get("fixtures/")


def get_player_summary(player_id):
    """Per-gameweek history and upcoming fixtures for one player."""
    return _get(f"element-summary/{player_id}/")


def get_entry(team_id):
    """A manager's team overview."""
    return _get(f"entry/{team_id}/")


def get_entry_picks(team_id, gameweek):
    """A manager's picks for a given gameweek."""
    return _get(f"entry/{team_id}/event/{gameweek}/picks/")


def get_entry_history(team_id):
    """A manager's season and transfer history."""
    return _get(f"entry/{team_id}/history/")
