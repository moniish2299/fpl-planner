from fpl_planner.llm_extract import extract_json, fetch_page_text

LINEUPS_URL = "https://www.rotowire.com/soccer/lineups.php"

LINEUP_SCHEMA = {
    "teams": [
        {
            "team": "string",
            "starters": ["string"],
            "out": ["string"],
            "doubtful": ["string"],
        }
    ]
}

_PROMPT = (
    "This page lists Premier League predicted/confirmed starting lineups for upcoming matches, "
    "plus injury reports. For every team shown, extract: its predicted/confirmed starting XI "
    "player names (as printed, e.g. 'M. Odegaard' or 'Bukayo Saka') as starters; any of that "
    "team's players explicitly marked OUT (injured, suspended, not playing this match) as out; "
    "and any marked doubtful/questionable/'QUES' as doubtful. Only include players clearly "
    "associated with that team, not the opponent."
)


def get_predicted_lineups():
    """Fetch RotoWire's Premier League lineups page and extract each team's
    predicted/confirmed starting XI plus OUT/doubtful tags.

    This is only meaningful for the very next unplayed gameweek - lineups
    aren't predicted more than a few days out, unlike the preseason/World
    Cup signals which are fixed historical data. Returns a list of
    {"team": str, "starters": [str], "out": [str], "doubtful": [str]}.
    """
    page_text = fetch_page_text(LINEUPS_URL, max_chars=60000)
    result = extract_json(_PROMPT, page_text, LINEUP_SCHEMA)
    return [t for t in result.get("teams", []) if t.get("team")]
