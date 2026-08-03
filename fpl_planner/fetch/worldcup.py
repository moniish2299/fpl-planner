from fpl_planner.llm_extract import extract_json, fetch_page_text

# Older World Cups eventually get their Final/Semis/Third-place matches split
# into their own dedicated Wikipedia articles, but a tournament that finished
# only weeks ago (like 2026) is still consolidated into the single main
# article - verified directly, no per-match article exists yet. So rather
# than discover separate articles (which was returning nothing), this reads
# the main tournament article directly and asks the model to focus on the
# relevant sections within it. The article is long (150k+ chars of visible
# text), but well within a cheap model's context window in one call.
LINEUP_SCHEMA = {"players": [{"name": "string", "team": "string", "minutes_estimate": "number"}]}


def _main_article_url(year):
    return f"https://en.wikipedia.org/wiki/{year}_FIFA_World_Cup"


def get_world_cup_minutes(year):
    """Returns a list of {"name", "team", "minutes_estimate"} for every player
    who featured in the Final/Semis/Third-place match - the subset with the
    least recovery time before Premier League preseason, which is what a
    fatigue signal actually needs.
    """
    url = _main_article_url(year)
    page_text = fetch_page_text(url, max_chars=250000)
    result = extract_json(
        f"This is the Wikipedia article for the {year} FIFA World Cup. Find the Final, both "
        f"Semi-finals, and the Third-place match specifically (they're near the end of the "
        f"'Knockout stage' section, not the group stage or earlier knockout rounds). List every "
        f"player who appeared as a starter or substitute in any of those matches, with your "
        f"best estimate of minutes played (a full match not going to extra time is 90, extra "
        f"time is 120) and which team/nation they played for.",
        page_text,
        LINEUP_SCHEMA,
    )
    return [p for p in result.get("players", []) if p.get("name")]
