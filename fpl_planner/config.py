import os

FPL_BASE_URL = "https://fantasy.premierleague.com/api"
UNDERSTAT_BASE_URL = "https://understat.com"
UNDERSTAT_LEAGUE = "EPL"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def get_team_id():
    return os.environ.get("FPL_TEAM_ID")


def get_understat_season():
    return os.environ.get("UNDERSTAT_SEASON", "2025")
