def detect_fixture_events(fixtures, total_teams=20):
    """Group fixtures by gameweek and find blank gameweeks (a team has no
    fixture) and double gameweeks (a team has two or more)."""
    counts_by_event = {}
    for f in fixtures:
        event = f.get("event")
        if event is None:
            continue
        counts = counts_by_event.setdefault(event, {})
        counts[f["team_h"]] = counts.get(f["team_h"], 0) + 1
        counts[f["team_a"]] = counts.get(f["team_a"], 0) + 1

    blanks, doubles = {}, {}
    for event, counts in counts_by_event.items():
        blank_teams = [t for t in range(1, total_teams + 1) if counts.get(t, 0) == 0]
        double_teams = [t for t, c in counts.items() if c >= 2]
        if blank_teams:
            blanks[event] = blank_teams
        if double_teams:
            doubles[event] = double_teams
    return blanks, doubles


def recommend_chips(fixtures, current_event=1, squad_team_ids=None, total_teams=20):
    """Chip timing suggestions from the fixture calendar: Free Hit for blank
    gameweeks, Wildcard/Bench Boost/Triple Captain around double gameweeks.
    Blank/double gameweeks are usually only visible once cup fixtures reshuffle
    the calendar mid-season, so an empty result pre-season is expected -
    a generic rule-of-thumb is returned in that case instead.
    """
    blanks, doubles = detect_fixture_events(fixtures, total_teams)
    recommendations = []

    for event in sorted(e for e in blanks if e >= current_event):
        teams = blanks[event]
        note = f"{len(teams)} team(s) have no fixture in GW{event}."
        if squad_team_ids:
            hit = len(squad_team_ids & set(teams))
            note += f" {hit} of your squad's teams are affected."
        recommendations.append({
            "chip": "Free Hit",
            "gameweek": event,
            "reason": note + " Free Hit lets you field a full XI for one week "
                              "without permanently changing your squad.",
        })

    for event in sorted(e for e in doubles if e >= current_event):
        teams = doubles[event]
        note = f"{len(teams)} team(s) play twice in GW{event}."
        if squad_team_ids:
            hit = len(squad_team_ids & set(teams))
            note += f" {hit} of your squad's teams are affected."
        recommendations.append({
            "chip": "Wildcard (1-2 GWs before) / Bench Boost or Triple Captain (during)",
            "gameweek": event,
            "reason": note + " Consider wildcarding beforehand to stock up on double-gameweek "
                              "players, then Bench Boost if most of your squad has two fixtures, "
                              "or Triple Captain on your best double-gameweek player.",
        })

    if not recommendations:
        recommendations.append({
            "chip": "Wildcard",
            "gameweek": None,
            "reason": "No blank/double gameweeks in the fixture list yet - the calendar usually only "
                      "reshuffles once cup competitions create clashes, so this is expected before/early "
                      "in the season. Rule of thumb: save your first wildcard for around GW4-8 once early "
                      "form and injuries are clearer, and your second for a good fixture swing later in "
                      "the season - re-run this once blanks/doubles appear in the fixture list.",
        })

    return recommendations
