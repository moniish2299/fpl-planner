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
# Requires an API key for the configured provider - these features skip
# gracefully if one isn't set.
LLM_PROVIDER = os.environ.get("FPL_PLANNER_LLM_PROVIDER", "gemini")

_DEFAULT_LLM_MODELS = {
    "gemini": "gemini-2.5-flash-lite",
    "anthropic": "claude-haiku-4-5-20251001",
}
LLM_MODEL = os.environ.get(
    "FPL_PLANNER_LLM_MODEL", _DEFAULT_LLM_MODELS.get(LLM_PROVIDER, "gemini-2.5-flash-lite")
)

# Per-provider env vars so switching FPL_PLANNER_LLM_PROVIDER doesn't require
# renaming your key - FPL_PLANNER_LLM_API_KEY overrides both if set.
_PROVIDER_API_KEY_VARS = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def get_team_id():
    return os.environ.get("FPL_TEAM_ID")


def get_understat_season():
    return os.environ.get("UNDERSTAT_SEASON", "2025")


def get_llm_api_key():
    generic = os.environ.get("FPL_PLANNER_LLM_API_KEY")
    if generic:
        return generic
    provider_var = _PROVIDER_API_KEY_VARS.get(LLM_PROVIDER)
    return os.environ.get(provider_var) if provider_var else None


def get_world_cup_year():
    return os.environ.get("FPL_PLANNER_WORLD_CUP_YEAR", "2026")
