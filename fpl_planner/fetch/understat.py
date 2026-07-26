import requests

from fpl_planner.config import UNDERSTAT_BASE_URL, UNDERSTAT_LEAGUE, USER_AGENT

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"})


def get_league_data(season):
    """Teams, players, and match data with underlying xG/xA/npxG stats for a
    league season, via Understat's internal getLeagueData endpoint (the data
    that used to be embedded in the league page's HTML is now loaded async)."""
    url = f"{UNDERSTAT_BASE_URL}/getLeagueData/{UNDERSTAT_LEAGUE}/{season}"
    headers = {"Referer": f"{UNDERSTAT_BASE_URL}/league/{UNDERSTAT_LEAGUE}/{season}"}
    response = _session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def get_league_players(season):
    """Underlying xG/xA/npxG stats for every player in the league for a season."""
    return get_league_data(season)["players"]
