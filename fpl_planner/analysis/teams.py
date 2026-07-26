import re
import unicodedata

_ALIASES = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "spurs": "tottenham",
    "newcastle": "newcastle united",
    "nott'm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers",
    "leeds": "leeds united",
    "west brom": "west bromwich albion",
}


def normalize(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().strip()
    name = _ALIASES.get(name, name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def match_teams(fpl_teams, understat_teams):
    """Match FPL teams to Understat teams by normalized name.

    Returns (matched, unmatched_fpl, leftover_understat):
      matched: {fpl_team_id: understat_team_dict}
      unmatched_fpl: [fpl_team_dict, ...]  -- promoted teams with no prior-season data
      leftover_understat: [understat_team_dict, ...]  -- relegated teams no longer in the league
    """
    by_norm = {normalize(t["title"]): t for t in understat_teams.values()}
    matched = {}
    unmatched_fpl = []
    for t in fpl_teams:
        key = normalize(t["name"])
        ut = by_norm.get(key)
        if ut is None:
            for norm_name, cand in by_norm.items():
                if key in norm_name or norm_name in key:
                    ut = cand
                    break
        if ut is not None:
            matched[t["id"]] = ut
        else:
            unmatched_fpl.append(t)

    used_understat_ids = {ut["id"] for ut in matched.values()}
    leftover_understat = [ut for ut in understat_teams.values() if ut["id"] not in used_understat_ids]
    return matched, unmatched_fpl, leftover_understat


def with_promoted_team_proxies(fpl_teams, understat_teams):
    """Fill in prior-season strength for newly promoted teams by substituting a
    relegated team's history, since promoted sides have no top-flight underlying
    data of their own. Pairs deterministically by team name so a re-run is stable;
    this is an approximation, not a scouted per-team mapping.
    """
    matched, unmatched_fpl, leftover_understat = match_teams(fpl_teams, understat_teams)

    if unmatched_fpl and leftover_understat:
        promoted_sorted = sorted(unmatched_fpl, key=lambda t: t["name"])
        relegated_sorted = sorted(leftover_understat, key=lambda t: t["title"])
        for i, promoted in enumerate(promoted_sorted):
            proxy = relegated_sorted[i % len(relegated_sorted)]
            matched[promoted["id"]] = proxy

    still_unmatched = [t["name"] for t in unmatched_fpl if t["id"] not in matched]
    proxied = {t["name"]: matched[t["id"]]["title"] for t in unmatched_fpl if t["id"] in matched}
    return matched, still_unmatched, proxied
