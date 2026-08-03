from fpl_planner.llm_extract import extract_json, fetch_page_text

# Official club sites turned out to be near-universally JavaScript SPAs -
# a plain GET returns an empty shell for the large majority of them (verified
# directly: ~15 of 20 return under 2KB of real text once script/style/svg are
# stripped), so no amount of prompt/parsing work fixes that. BBC Sport's team
# pages are server-rendered, follow one consistent URL pattern for every club
# (including Man City/Man Utd, whose own sites block scraping outright), and
# already show recent pre-season friendly results with inline match-report
# prose for the ones BBC covered in writing - exactly what the LLM needs to
# read, in a single request per club.
BBC_SLUGS = {
    "Arsenal": "arsenal",
    "Aston Villa": "aston-villa",
    "Bournemouth": "afc-bournemouth",
    "Brentford": "brentford",
    "Brighton": "brighton-and-hove-albion",
    "Chelsea": "chelsea",
    "Coventry City": "coventry-city",
    "Crystal Palace": "crystal-palace",
    "Everton": "everton",
    "Fulham": "fulham",
    "Hull City": "hull-city",
    "Ipswich Town": "ipswich-town",
    "Leeds": "leeds-united",
    "Liverpool": "liverpool",
    "Man City": "manchester-city",
    "Man Utd": "manchester-united",
    "Newcastle": "newcastle-united",
    "Nott'm Forest": "nottingham-forest",
    "Spurs": "tottenham-hotspur",
    "Sunderland": "sunderland",
}

LINEUP_SCHEMA = {
    "matches_seen": "number",
    "players": [{"name": "string", "minutes_estimate": "number"}],
}

_PROMPT = (
    "This is a BBC Sport team page. It lists this club's recent pre-season friendly matches "
    "(labelled things like 'Club Friendlies', not competitive fixtures) with scores, and some "
    "of them have short match-report text below them describing the game. First, count how "
    "many completed pre-season friendly matches are shown at all (whether or not they have a "
    "report) as matches_seen. Then, from any match-report text present, list every player from "
    "THIS club's own squad (not the opponent) mentioned as starting, coming on as a substitute, "
    "or playing a named portion of a match, with your best estimate of minutes played (a full "
    "match is ~90 unless the text says they were subbed off or came on later). If no report "
    "text exists on the page at all, return an empty players list but still report matches_seen."
)


def get_club_preseason_appearances(team_name):
    """Returns (appearances, matches_covered) where appearances is a list of
    {"name": str, "minutes_estimate": float} and matches_covered is how many
    completed preseason friendlies the page showed (used as the minutes
    denominator downstream) - not every friendly has report text, so
    appearances only covers the subset that did.
    """
    slug = BBC_SLUGS[team_name]
    url = f"https://www.bbc.com/sport/football/teams/{slug}"
    page_text = fetch_page_text(url, max_chars=40000)
    result = extract_json(_PROMPT, page_text, LINEUP_SCHEMA)

    appearances = [
        {"name": p["name"], "minutes_estimate": p.get("minutes_estimate") or 0}
        for p in result.get("players", [])
        if p.get("name")
    ]
    matches_covered = int(result.get("matches_seen") or 0)
    return appearances, matches_covered
