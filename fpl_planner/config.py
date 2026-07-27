import os

FPL_BASE_URL = "https://fantasy.premierleague.com/api"
UNDERSTAT_BASE_URL = "https://understat.com"
UNDERSTAT_LEAGUE = "EPL"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Used for LLM-assisted extraction of lineup/minutes data out of prose match
# reports and Wikipedia squad pages (no structured API exists for either).
# Requires the user's own ANTHROPIC_API_KEY - these features skip gracefully
# if it's not set.
LLM_MODEL = os.environ.get("FPL_PLANNER_LLM_MODEL", "claude-haiku-4-5-20251001")


def get_team_id():
    return os.environ.get("FPL_TEAM_ID")


def get_understat_season():
    return os.environ.get("UNDERSTAT_SEASON", "2025")


def get_anthropic_api_key():
    return os.environ.get("ANTHROPIC_API_KEY")


def get_world_cup_year():
    return os.environ.get("FPL_PLANNER_WORLD_CUP_YEAR", "2026")
