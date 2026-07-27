from urllib.parse import urljoin

from fpl_planner.llm_extract import extract_json, fetch_page_text

# Deepest-into-the-tournament matches are what matter for fatigue - a
# group-stage-only player has had a normal summer off by the time preseason
# starts. Rather than hardcode Wikipedia article titles for a specific year
# (they don't follow one fixed pattern and this file is meant to work for
# whichever World Cup year is configured), discover them from the main
# tournament article, same two-stage discover-then-extract pattern as
# fetch/preseason.py.
MATCH_LINK_SCHEMA = {"match_urls": ["string"]}
LINEUP_SCHEMA = {"players": [{"name": "string", "team": "string", "minutes_estimate": "number"}]}


def _main_article_url(year):
    return f"https://en.wikipedia.org/wiki/{year}_FIFA_World_Cup"


def find_deep_knockout_match_links(year):
    url = _main_article_url(year)
    page_text = fetch_page_text(url, max_chars=25000)
    result = extract_json(
        f"This is the Wikipedia article for the {year} FIFA World Cup. Find links to the "
        f"dedicated Wikipedia articles for the tournament Final, both Semi-finals, and the "
        f"Third-place match (not the group stage or earlier rounds).",
        page_text,
        MATCH_LINK_SCHEMA,
    )
    return [urljoin(url, href) for href in result.get("match_urls", [])]


def extract_match_lineups(match_url):
    page_text = fetch_page_text(match_url, max_chars=25000)
    result = extract_json(
        "This is a Wikipedia article for a single football match. List every player who "
        "appears in either team's starting lineup or as a substitute who came on, with your "
        "best estimate of minutes played (a full match not going to extra time is 90, extra "
        "time is 120) and which team/nation they played for.",
        page_text,
        LINEUP_SCHEMA,
    )
    return result.get("players", [])


def get_world_cup_minutes(year):
    """Returns a list of {"name", "team", "minutes_estimate"} for every player
    who featured in the Final/Semis/Third-place match - the subset with the
    least recovery time before Premier League preseason, which is what a
    fatigue signal actually needs.
    """
    match_links = find_deep_knockout_match_links(year)

    totals = {}
    for link in match_links:
        for p in extract_match_lineups(link):
            name = p.get("name")
            if not name:
                continue
            key = (name, p.get("team", ""))
            totals[key] = totals.get(key, 0) + (p.get("minutes_estimate") or 0)

    return [
        {"name": name, "team": team, "minutes_estimate": minutes}
        for (name, team), minutes in totals.items()
    ]
