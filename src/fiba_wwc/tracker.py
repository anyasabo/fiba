"""Scrape FIBA's team pages for the national squads.

Every nation has a page at ``/en/events/<event>/teams/<slug>``, and the same
Next.js flight payload the game pages use carries a structured roster object on
it: a player record per squad member with a shirt number, a club, and -- the
part that matters -- ``isOnFinalRoster``. That flag is FIBA's own answer to
"has this federation cut to a playing twelve", so ``final_twelve`` below is a
reading of the source rather than an inference from how long a list is.

This replaced the roster-tracker news article, which was prose in a Contentful
rich-text document and went stale without any outward sign: with the tournament
under way and all sixteen squads locked, it still described eight of them as
preselect pools, and nothing in the data said otherwise.

What it is good for and what it is not
--------------------------------------
The team page is authoritative for *who is on the twelve*, and it carries each
player's club, so it can also say which of them play in the WNBA. That goes
under ``wnba`` and lets ``fiba-wwc check`` catch a WNBA player in a squad that
data/rosters.yaml has missed, and one of ours who is not in the squad at all.

It cannot see a WNBA developmental player whose FIBA club is her European one
-- Elizabeth Balogun reads as Valencia here, not New York -- so ``wnba`` is a
floor, not the whole mapping. data/rosters.yaml still owns that and stays
hand-edited.

A twelve is not frozen once the tournament starts: an injury replacement
rewrites one mid-event. So this is built to be re-run. Output is merged into
data/fiba_rosters.yaml a nation at a time and committed, which means a squad
changing under us shows up as a reviewable ``git diff`` -- and fails ``check``
until rosters.yaml is brought back in line.
"""

from __future__ import annotations

import re
import unicodedata

import httpx
import yaml

from .paths import FIBA_ROSTERS_YAML, SCHEDULE_YAML, WNBA_TEAMS_YAML
from .scrape import BASE, UA, fetch, find_values, flight_text
from .urls import clean_url

#: A squad this size has been cut to a playing roster rather than a pool.
FINAL_SQUAD_SIZE = 12


# --------------------------------------------------------------------------- #
# parsing the team pages
# --------------------------------------------------------------------------- #


def extract_team_slugs(html: str) -> dict[str, str]:
    """``{FIBA tricode: url slug}`` from the event's teams listing page."""
    for value in find_values(flight_text(html), "teams"):
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and {"code", "slug"} <= value[0].keys()
        ):
            return {t["code"]: t["slug"] for t in value}
    return {}


def extract_roster(html: str) -> dict | None:
    """The roster object from one team page. None means "could not parse".

    The page carries a second thing under the same ``roster`` key -- the i18n
    label dictionary for the roster table -- so this tests the shape rather
    than taking the first hit.
    """
    for value in find_values(flight_text(html), "roster"):
        players = value.get("players") if isinstance(value, dict) else None
        if isinstance(players, list) and players and isinstance(players[0], dict):
            return value
    return None


def squad_entry(roster: dict, *, source: str, clubs: dict[str, str]) -> dict:
    """One nation's record for data/fiba_rosters.yaml.

    ``clubs`` maps a WNBA club's full name to its abbreviation; a player whose
    FIBA club is one of them is a WNBA player we can name without a hand-edit.
    """
    players = roster["players"]
    names = [f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() for p in players]
    final = sum(1 for p in players if p.get("isOnFinalRoster"))
    return {
        "players": names,
        "count": len(names),
        "final_twelve": len(names) == final == FINAL_SQUAD_SIZE,
        "wnba": {
            name: clubs[p["clubName"]]
            for name, p in zip(names, players, strict=True)
            if p.get("clubName") in clubs
        },
        "source": source,
    }


# --------------------------------------------------------------------------- #
# matching our player names to FIBA's
# --------------------------------------------------------------------------- #


def normalise(name: str) -> list[str]:
    """Casefold, strip diacritics and punctuation, split into sorted tokens.

    Sorted because FIBA writes Chinese names given-name-first ("Xu Han") where
    we follow Chinese and WNBA convention ("Han Xu"); comparing token *sets*
    makes the two agree without either side being rewritten.
    """
    text = name.replace("’", "'").replace("‘", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return sorted(t for t in re.sub(r"[^a-z ]", " ", text.lower()).split() if t)


def _edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein: counts a transposition as one edit, not two.

    "Sowha" for "Sowah" is a single slip of the fingers and has to score as one.
    """
    d: dict[tuple[int, int], int] = {(-1, -1): 0}
    for i in range(len(a) + 1):
        d[i, -1] = i + 1
    for j in range(len(b) + 1):
        d[-1, j] = j + 1
    for i, ca in enumerate(a):
        for j, cb in enumerate(b):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ca != cb))
            if i and j and ca == b[j - 1] and a[i - 1] == cb:
                d[i, j] = min(d[i, j], d[i - 2, j - 2] + 1)
    return d[len(a) - 1, len(b) - 1]


def _token_matches(a: str, b: str) -> bool:
    if a == b:
        return True
    # "Steph" for "Stephanie". Length floor keeps short tokens from colliding.
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    # One typo. Only on tokens long enough that a single edit is not most of it,
    # which matters because Chinese given names are two or three letters.
    return min(len(a), len(b)) >= 5 and _edit_distance(a, b) <= 1


def names_match(ours: str, theirs: str) -> bool:
    """Whether two spellings plausibly denote the same player.

    Deliberately tolerant: FIBA strips some diacritics but not others, has its
    own typos, and abbreviates given names. Tolerance is safe here only because
    an inexact match is *reported* by the check rather than silently accepted.
    """
    a, b = normalise(ours), normalise(theirs)
    if len(a) != len(b):
        return False
    taken: set[int] = set()
    for token in a:
        for i, other in enumerate(b):
            if i not in taken and _token_matches(token, other):
                taken.add(i)
                break
        else:
            return False
    return True


def find_player(name: str, squad: list[str], *, alias: str | None = None) -> str | None:
    """The squad entry denoting this player, or None.

    ``alias`` is data/rosters.yaml's ``fiba_name``: an explicit "yes, FIBA
    spells it this way, stop reporting it" for divergences we have reviewed and
    decided to keep -- a stale surname, a stripped accent, our fuller given name.
    """
    if alias:
        return next((n for n in squad if n == alias), None)
    return next((n for n in squad if names_match(name, n)), None)


# --------------------------------------------------------------------------- #
# scrape + persist
# --------------------------------------------------------------------------- #


def scrape_squads(*, refresh: bool = False) -> tuple[dict[str, dict], list[str]]:
    """Fetch every competing nation's team page, keyed on our nation codes."""
    schedule = yaml.safe_load(SCHEDULE_YAML.read_text(encoding="utf-8"))
    event_slug = schedule["tournament"]["fiba_event_slug"]
    clubs = {
        spec["name"]: abbr
        for abbr, spec in yaml.safe_load(WNBA_TEAMS_YAML.read_text(encoding="utf-8")).items()
    }

    entries: dict[str, dict] = {}
    failures: list[str] = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
        listing = fetch(client, f"{BASE}/en/events/{event_slug}/teams", refresh=refresh)
        slugs = extract_team_slugs(listing)
        if not slugs:
            raise RuntimeError(
                "No teams array found on the listing page -- FIBA's page structure "
                "has changed and tracker.py needs updating."
            )

        # Driven by our own team list, so a nation FIBA adds or renames surfaces
        # as a failure here rather than silently becoming a squad we never had.
        for code in sorted(schedule["teams"]):
            slug = slugs.get(code)
            if slug is None:
                failures.append(f"{code}: FIBA's listing has no team page")
                continue
            url = clean_url(f"{BASE}/en/events/{event_slug}/teams/{slug}")
            try:
                roster = extract_roster(fetch(client, url, refresh=refresh))
            except Exception as exc:  # network, 404, redirect loop
                failures.append(f"{code}: {exc}")
                continue
            if roster is None:
                failures.append(f"{code}: no roster block on the team page")
                continue
            entries[code] = squad_entry(roster, source=url, clubs=clubs)

    return entries, failures


def load_squads() -> dict[str, dict]:
    if not FIBA_ROSTERS_YAML.exists():
        return {}
    return yaml.safe_load(FIBA_ROSTERS_YAML.read_text(encoding="utf-8")) or {}


def merge_and_write(entries: dict[str, dict]) -> dict[str, dict]:
    """Merge over what is on file, so a partial parse never destroys good data."""
    merged = load_squads()
    merged.update(entries)
    FIBA_ROSTERS_YAML.write_text(
        "# Generated by `fiba-wwc scrape-rosters` -- do not hand-edit.\n"
        "#\n"
        "# National squads exactly as FIBA's own team pages publish them.\n"
        "# `final_twelve` is FIBA's isOnFinalRoster flag across all twelve, not a\n"
        "# guess from the list's length. `wnba` names the squad members whose FIBA\n"
        "# club is a WNBA club -- a floor, not the whole mapping, since a\n"
        "# developmental player is listed at her European club.\n"
        "#\n"
        "# Committed so that re-running the scrape shows up as a reviewable diff:\n"
        "# a squad that changes mid-tournament is the thing worth noticing.\n\n"
        + yaml.safe_dump(merged, allow_unicode=True, sort_keys=True, width=88),
        encoding="utf-8",
    )
    return merged
