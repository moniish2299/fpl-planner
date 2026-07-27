import re
import unicodedata


def normalize(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().strip()
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _token_score(target_tokens, candidate_tokens):
    """Full-token matches count 1; a single-letter token matching a
    candidate's initial (e.g. "j" vs "jacob") counts 0.5, to handle bylines
    like "J.Murphy" against FPL's "Jacob Murphy"."""
    score = 0.0
    for t in target_tokens:
        for c in candidate_tokens:
            if t == c:
                score += 1.0
            elif len(t) == 1 and c.startswith(t):
                score += 0.5
            elif len(c) == 1 and t.startswith(c):
                score += 0.5
    return score


def match_player(candidates, external_name, min_score=1.0):
    """Best-effort match of a name from external prose (match report, WC
    lineup) against a *pre-scoped* list of FPL player dicts (e.g. just one
    club's squad) - scoping to a small candidate pool is what keeps this
    reliable, unlike a global 500+ player fuzzy match.

    `candidates` items need `web_name` and either `full_name` or
    `first_name`/`second_name`. Returns the best-matching candidate or None.
    """
    target = normalize(external_name)
    if not target:
        return None
    target_tokens = set(target.split())

    best, best_score = None, 0.0
    for p in candidates:
        full_name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('second_name', '')}"
        for form in (normalize(full_name), normalize(p.get("web_name", ""))):
            if form and form == target:
                return p
        candidate_tokens = normalize(full_name).split()
        score = _token_score(target_tokens, candidate_tokens)
        if score > best_score:
            best_score, best = score, p

    return best if best_score >= min_score else None


def match_all(candidates, external_entries, name_key="name", min_score=1.0):
    """Match a list of external entries (each with a name_key) against
    candidates. Returns (matched, unmatched) where matched is a list of
    (external_entry, candidate) pairs and unmatched is the list of external
    entries with no confident match."""
    matched, unmatched = [], []
    for entry in external_entries:
        candidate = match_player(candidates, entry[name_key], min_score=min_score)
        if candidate:
            matched.append((entry, candidate))
        else:
            unmatched.append(entry)
    return matched, unmatched
