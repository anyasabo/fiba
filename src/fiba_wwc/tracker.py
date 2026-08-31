"""Scrape FIBA's official roster tracker for the national squads.

The tracker is a news article, not a data endpoint: a Contentful rich-text
document embedded in the same Next.js flight payload the game pages use. Each
nation is a ``heading-2`` followed by one paragraph of comma-separated names and
an optional "Announcement" hyperlink to the federation's own release.

What it is good for and what it is not
--------------------------------------
It is the only official source for **which names a federation has published**,
and the article says so itself:

    Rosters displayed on this page have been extracted from information made
    public by the relevant National Member Federations but do not necessarily
    correspond to the rosters that will play in the FIBA Women's Basketball
    World Cup 2026.

So it does NOT decide ``status`` in data/rosters.yaml. A federation can confirm
an individual player long before it publishes a final twelve, and the tracker
cannot express that. ``final_twelve`` here means only "this list is exactly 12
names long" -- a useful signal that a squad has been cut, never a per-player
verdict.

It also carries no club affiliation, so it can never tell us who is a WNBA
player. data/rosters.yaml owns that mapping and stays hand-edited.

The Announcement link is NOT a finality signal, despite looking like one:
Hungary (25 names), Spain (21) and Türkiye (20) all link to a federation release
announcing a *pool*, while China, Germany and Nigeria list a pool with no link.

Output is merged into data/fiba_rosters.yaml and committed, so that re-running
this as federations name their squads shows up as a reviewable ``git diff`` --
a nation dropping from 23 names to 12 is the thing worth noticing.
"""

from __future__ import annotations

import re
import unicodedata

import httpx
import yaml

from .paths import FIBA_ROSTERS_YAML, SCHEDULE_YAML
from .scrape import BASE, UA, fetch, find_values, flight_text
from .urls import clean_url

TRACKER_URL = (
    f"{BASE}/en/events/fiba-womens-basketball-world-cup-2026/news"
    "/roster-tracker-fiba-womens-basketball-world-cup-2026"
)

#: A squad this size has been cut to a playing roster rather than a pool.
FINAL_SQUAD_SIZE = 12


# --------------------------------------------------------------------------- #
# parsing the rich-text document
# --------------------------------------------------------------------------- #


def _node_text(node: dict) -> str:
    if node.get("nodeType") == "text":
        return node.get("value", "")
    return "".join(_node_text(c) for c in node.get("content", []))


def _richtext_body(html: str) -> list[dict] | None:
    """The article body: the longest "content" array that has nation headings."""
    bodies = [
        v
        for v in find_values(flight_text(html), "content")
        if isinstance(v, list)
        and any(isinstance(n, dict) and n.get("nodeType") == "heading-2" for n in v)
    ]
    return max(bodies, key=len) if bodies else None


def extract_squads(html: str) -> dict[str, dict]:
    """``{nation name: {"players": [...], "source": url|None}}``.

    Keyed on FIBA's own heading text; :func:`scrape_squads` maps that onto our
    nation codes.
    """
    body = _richtext_body(html)
    if body is None:
        return {}

    squads: dict[str, dict] = {}
    heading: str | None = None
    for node in body:
        kind = node.get("nodeType")
        if kind == "heading-2":
            heading = _node_text(node).strip()
        elif kind == "paragraph" and heading:
            # Names run up to the "(Announcement)" link; the trailing paragraph
            # of disclaimer prose has no heading above it and is never reached.
            text = re.sub(r"\(.*", "", _node_text(node))
            players = [n.strip() for n in text.split(",") if n.strip()]
            links = [
                c["data"]["uri"]
                for c in node.get("content", [])
                if c.get("nodeType") == "hyperlink" and c.get("data", {}).get("uri")
            ]
            if players:
                squads[heading] = {
                    "players": players,
                    "source": clean_url(links[0]) if links else None,
                }
            heading = None
    return squads


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
    """Fetch the tracker and key it on our nation codes."""
    teams = yaml.safe_load(SCHEDULE_YAML.read_text(encoding="utf-8"))["teams"]
    code_of = {spec["name"]: code for code, spec in teams.items()}

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
        html = fetch(client, TRACKER_URL, refresh=refresh)

    squads = extract_squads(html)
    entries, unknown = {}, []
    for heading, squad in squads.items():
        code = code_of.get(heading)
        if code is None:
            unknown.append(heading)
            continue
        entries[code] = {
            "players": squad["players"],
            "count": len(squad["players"]),
            "final_twelve": len(squad["players"]) == FINAL_SQUAD_SIZE,
            "source": squad["source"],
        }
    return entries, unknown


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
        "# National squads exactly as FIBA's roster tracker publishes them. FIBA's\n"
        "# own disclaimer: these are what federations have made public and do not\n"
        "# necessarily match the twelve who will play. `final_twelve` means the\n"
        "# list is 12 names long, nothing more -- it never decides a player's\n"
        "# `status` in rosters.yaml, which stays hand-owned.\n"
        "#\n"
        "# Committed so that re-running the scrape as federations name their\n"
        "# squads shows up as a reviewable diff.\n\n"
        + yaml.safe_dump(merged, allow_unicode=True, sort_keys=True, width=88),
        encoding="utf-8",
    )
    return merged
