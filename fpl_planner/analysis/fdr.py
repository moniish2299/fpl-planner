import bisect

from fpl_planner.analysis.teams import with_promoted_team_proxies

# Last season's Understat data is the only signal available pre-season, but
# this season's actual results are a truer read on a team's current level -
# weight the prior-season baseline out and this season's results in,
# linearly, over the first 5 gameweeks (fully current-season by GW6).
_TEAM_STRENGTH_FADE_GWS = 5


def _avg(matches, key):
    vals = [float(m[key]) for m in matches]
    return sum(vals) / len(vals) if vals else None


def _last_season_weight(from_event):
    return max(0.0, min(1.0, (_TEAM_STRENGTH_FADE_GWS + 1 - from_event) / _TEAM_STRENGTH_FADE_GWS))


def _team_rates(ut):
    """ut: one Understat team entry, with a 'history' list of per-match xG/
    xGA. Returns raw attack/defense rates split by home/away - defense
    negated so higher always means 'stronger', consistent with attack.
    A split with no matches yet (e.g. this season, before that team's first
    game) comes back None rather than 0, so it blends as "no data" rather
    than "team is terrible"."""
    home = [m for m in ut["history"] if m["h_a"] == "h"]
    away = [m for m in ut["history"] if m["h_a"] == "a"]
    conceded_home, conceded_away = _avg(home, "xGA"), _avg(away, "xGA")
    return {
        "attack_home": _avg(home, "xG"),
        "attack_away": _avg(away, "xG"),
        "defense_home": -conceded_home if conceded_home is not None else None,
        "defense_away": -conceded_away if conceded_away is not None else None,
    }


def _blend_rate(last_value, current_value, last_season_weight):
    if current_value is None:
        return last_value
    if last_value is None:
        return current_value
    return last_season_weight * last_value + (1 - last_season_weight) * current_value


def _scale_1_to_5(values):
    """Map a dict of id->raw value onto a 1-5 scale by percentile, matching
    the FPL FDR convention: 5 is hardest (highest raw value)."""
    ids = [k for k, v in values.items() if v is not None]
    sorted_vals = sorted(values[k] for k in ids)
    result = {}
    for k in ids:
        percentile = bisect.bisect_right(sorted_vals, values[k]) / len(sorted_vals)
        result[k] = min(5, max(1, int(percentile * 5) + (1 if percentile < 1 else 0)))
    return result


def build_team_strength(bootstrap, understat_teams, current_understat_teams=None, from_event=1):
    """Per-team attack/defense strength split by home/away, derived from prior
    season Understat xG data (FPL's own strength_* fields are blank pre-season).
    Promoted teams get a relegated team's numbers substituted as a proxy.

    When `current_understat_teams` (this season's Understat data, sparse
    early on) is given, it's blended in against the prior-season baseline,
    weighted by `_last_season_weight(from_event)` - prior season dominates
    at GW1, this season's actual results dominate from GW6 on. A team with
    no matches yet this season (or missing from `current_understat_teams`
    entirely) just keeps its prior-season rate until it has some.

    Returns {
      "attack": {team_id: {"home": 1-5, "away": 1-5}},   # higher = stronger attack
      "defense": {team_id: {"home": 1-5, "away": 1-5}},  # higher = stronger defense
      "unmatched_teams": [...], "proxied_teams": {...},
    }
    """
    fpl_teams = bootstrap["teams"]
    matched, unmatched, proxied = with_promoted_team_proxies(fpl_teams, understat_teams)
    current_matched = {}
    if current_understat_teams:
        current_matched, _, _ = with_promoted_team_proxies(fpl_teams, current_understat_teams)
    last_season_weight = _last_season_weight(from_event)

    raw_attack, raw_defense = {}, {}
    for t in fpl_teams:
        ut = matched.get(t["id"])
        if ut is None:
            continue
        last = _team_rates(ut)
        current = _team_rates(current_matched[t["id"]]) if t["id"] in current_matched else {}
        for split in ("home", "away"):
            raw_attack[(t["id"], split)] = _blend_rate(
                last[f"attack_{split}"], current.get(f"attack_{split}"), last_season_weight
            )
            raw_defense[(t["id"], split)] = _blend_rate(
                last[f"defense_{split}"], current.get(f"defense_{split}"), last_season_weight
            )

    attack_scaled = _scale_1_to_5(raw_attack)
    defense_scaled = _scale_1_to_5(raw_defense)

    attack = {}
    defense = {}
    for t in fpl_teams:
        tid = t["id"]
        attack[tid] = {"home": attack_scaled.get((tid, "home")), "away": attack_scaled.get((tid, "away"))}
        defense[tid] = {"home": defense_scaled.get((tid, "home")), "away": defense_scaled.get((tid, "away"))}

    return {
        "attack": attack,
        "defense": defense,
        "unmatched_teams": unmatched,
        "proxied_teams": proxied,
    }


def fixture_ratings(fixtures, strength):
    """Per-fixture custom FDR, split by attacking difficulty (for FWD/MID/GK
    attacking returns) and defending difficulty (for DEF/GK clean sheet odds),
    for both sides of each fixture."""
    ratings = []
    for f in fixtures:
        h, a = f["team_h"], f["team_a"]
        h_defense = strength["defense"].get(h, {})
        a_defense = strength["defense"].get(a, {})
        h_attack = strength["attack"].get(h, {})
        a_attack = strength["attack"].get(a, {})
        ratings.append({
            "event": f.get("event"),
            "kickoff_time": f.get("kickoff_time"),
            "team_h": h,
            "team_a": a,
            # difficulty of scoring against the opponent, given where the match is played
            "home_attack_fdr": a_defense.get("away"),
            "away_attack_fdr": h_defense.get("home"),
            # difficulty of keeping a clean sheet against the opponent
            "home_defense_fdr": a_attack.get("away"),
            "away_defense_fdr": h_attack.get("home"),
        })
    return ratings


def upcoming_team_fdr(fixture_ratings_list, num_gameweeks=5, from_event=1):
    """Average attack/defense FDR per team over the next N gameweeks starting
    at from_event. Returns {team_id: {"attack": float, "defense": float, "fixtures": int}}."""
    horizon = range(from_event, from_event + num_gameweeks)
    totals = {}
    for r in fixture_ratings_list:
        if r["event"] not in horizon:
            continue
        for side, team_key, att_key, def_key in (
            ("h", "team_h", "home_attack_fdr", "home_defense_fdr"),
            ("a", "team_a", "away_attack_fdr", "away_defense_fdr"),
        ):
            tid = r[team_key]
            att, dfn = r[att_key], r[def_key]
            if att is None or dfn is None:
                continue
            bucket = totals.setdefault(tid, {"attack_sum": 0.0, "defense_sum": 0.0, "fixtures": 0})
            bucket["attack_sum"] += att
            bucket["defense_sum"] += dfn
            bucket["fixtures"] += 1

    result = {}
    for tid, bucket in totals.items():
        n = bucket["fixtures"]
        result[tid] = {
            "attack": bucket["attack_sum"] / n,
            "defense": bucket["defense_sum"] / n,
            "fixtures": n,
        }
    return result
