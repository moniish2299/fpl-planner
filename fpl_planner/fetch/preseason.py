from urllib.parse import urljoin

from fpl_planner.llm_extract import extract_json, fetch_page_text

# One fixtures/results URL per club - the actual friendly reports are prose
# news articles with no consistent HTML structure across clubs, so link
# discovery and lineup extraction are both done via LLM rather than per-club
# scraping logic. Man City/Man Utd block scraping outright (403) and are
# left out; a missing club here just means that club is skipped in fetch().
CLUB_SITES = {
    "Arsenal": "https://www.arsenal.com/fixtures",
    "Aston Villa": "https://www.avfc.co.uk/fixtures/first-team",
    "Bournemouth": "https://www.afcb.co.uk/fixtures-results/",
    "Brentford": "https://www.brentfordfc.com/matches",
    "Brighton": "https://www.brightonandhovealbion.com/fixtures/first-team",
    "Chelsea": "https://www.chelseafc.com/en/matches/mens-fixtures-and-results",
    "Coventry City": "https://www.ccfc.co.uk/matches/",
    "Crystal Palace": "https://www.cpfc.co.uk/matches/",
    "Everton": "https://www.evertonfc.com/fixtures",
    "Fulham": "https://www.fulhamfc.com/fixtures-results",
    "Hull City": "https://www.wearehullcity.co.uk/matches/fixtures/",
    "Ipswich Town": "https://www.itfc.co.uk/matches/",
    "Leeds": "https://www.leedsunited.com/fixtures-results/",
    "Liverpool": "https://www.liverpoolfc.com/fixtures",
    "Newcastle": "https://www.newcastleunited.com/en/matches/",
    "Nott'm Forest": "https://www.nottinghamforest.co.uk/match-centre/fixtures-results/",
    "Spurs": "https://www.tottenhamhotspur.com/matches/",
    "Sunderland": "https://www.safc.com/matches/",
}

MAX_REPORTS_PER_CLUB = 3

LINK_SCHEMA = {"report_urls": ["string"]}
LINEUP_SCHEMA = {"players": [{"name": "string", "minutes_estimate": "number"}]}


def find_report_links(fixtures_url):
    page_text = fetch_page_text(fixtures_url)
    result = extract_json(
        "This is a football club's fixtures/results page. Find links to this preseason's "
        "completed friendly match reports (preseason/pre-season friendlies only, not official "
        "competition matches). Return the href values as they appear in the HTML.",
        page_text,
        LINK_SCHEMA,
    )
    return [urljoin(fixtures_url, href) for href in result.get("report_urls", [])]


def extract_lineup(report_url):
    page_text = fetch_page_text(report_url)
    result = extract_json(
        "This is a football match report for a preseason friendly. List every player "
        "mentioned as starting, coming on as a substitute, or playing a named half/portion "
        "of the match, with your best estimate of minutes played (a full match is ~90, a "
        "single half is ~45). Use the name as written in the article.",
        page_text,
        LINEUP_SCHEMA,
    )
    return result.get("players", [])


def get_club_preseason_appearances(team_name):
    """Returns (appearances, matches_covered) where appearances is a list of
    {"name": str, "minutes_estimate": float} across up to MAX_REPORTS_PER_CLUB
    friendlies, aggregated per player (summed across matches).
    """
    fixtures_url = CLUB_SITES[team_name]
    report_links = find_report_links(fixtures_url)[:MAX_REPORTS_PER_CLUB]

    totals = {}
    matches_covered = 0
    for link in report_links:
        players = extract_lineup(link)
        if not players:
            continue
        matches_covered += 1
        for p in players:
            name = p.get("name")
            minutes = p.get("minutes_estimate") or 0
            if not name:
                continue
            totals[name] = totals.get(name, 0) + minutes

    appearances = [{"name": name, "minutes_estimate": minutes} for name, minutes in totals.items()]
    return appearances, matches_covered
