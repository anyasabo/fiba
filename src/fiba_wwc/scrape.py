"""Scrape fiba.basketball for official game links, venues and broadcast listings.

The FIBA site is a Next.js app: the pages render client-side, but every page ships
its data as a React flight payload inside ``self.__next_f.push([1,"<json>"])``
calls. We concatenate those chunks and pull JSON values out by key.

This is undocumented and WILL break when FIBA redesigns. Two containment measures:
the parsing lives only in this module, and results are MERGED into
data/fiba_scraped.yaml so a failed run never destroys previously good data.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import yaml

from .paths import CACHE, SCRAPED_YAML
from .urls import clean_url

BASE = "https://www.fiba.basketball"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# FIBA parks unresolved knockout games at 22:00 UTC on the day *before* their round
# opens, as a "to be announced" sentinel. Never trust those times.
TBD_SENTINEL_HOUR = 22


# --------------------------------------------------------------------------- #
# flight payload extraction
# --------------------------------------------------------------------------- #


def flight_text(html: str) -> str:
    """Concatenate every Next.js flight chunk into one searchable string."""
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,(".*?")\]\)', html, re.S):
        try:
            chunks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return "".join(chunks)


def find_values(text: str, key: str):
    """Yield every JSON value that appears as the value of ``"key":``."""
    decoder = json.JSONDecoder()
    for m in re.finditer(rf'"{re.escape(key)}"\s*:', text):
        try:
            value, _ = decoder.raw_decode(text, m.end())
        except json.JSONDecodeError:
            continue
        yield value


def extract_games(html: str) -> list[dict]:
    """The games array from the event's games listing page."""
    for value in find_values(flight_text(html), "games"):
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and "gameId" in value[0]
        ):
            return value
    return []


def extract_broadcasters(html: str) -> list[dict] | None:
    """Broadcasters from a single game page. None means "could not parse"."""
    for value in find_values(flight_text(html), "broadcasters"):
        if isinstance(value, list) and all(isinstance(b, dict) for b in value):
            return value
    return None


# --------------------------------------------------------------------------- #
# matching FIBA games to our schedule numbers
# --------------------------------------------------------------------------- #

# Knockout gameNames look like "29922-25-A" -- the middle field is FIBA's own
# global game number, which matches ours (25..36). Group games are "29919-A-1",
# per-group, so those get matched on team codes instead.
KNOCKOUT_NAME = re.compile(r"^\d+-(\d{2})-[A-Z]$")


def match_number(game: dict, schedule_games: list[dict]) -> int | None:
    name = game.get("gameName") or ""
    if m := KNOCKOUT_NAME.match(name):
        number = int(m.group(1))
        return number if any(g["number"] == number for g in schedule_games) else None

    a = (game.get("teamA") or {}).get("code")
    b = (game.get("teamB") or {}).get("code")
    if not (a and b):
        return None
    hits = [g["number"] for g in schedule_games if g.get("home") == a and g.get("away") == b]
    return hits[0] if len(hits) == 1 else None


def game_page_url(game: dict, event_slug: str) -> str:
    a = (game.get("teamA") or {}).get("code")
    b = (game.get("teamB") or {}).get("code")
    slug = f"{game['gameId']}-{a}-{b}" if a and b else str(game["gameId"])
    return f"{BASE}/en/events/{event_slug}/games/{slug}"


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #


def fetch(client: httpx.Client, url: str, *, refresh: bool = False) -> str:
    """GET with an on-disk cache, so iterating on the parser costs no requests."""
    CACHE.mkdir(exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9._-]", "_", url)[-180:]
    path = CACHE / f"{key}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    resp = client.get(url)
    resp.raise_for_status()
    path.write_text(resp.text, encoding="utf-8")
    time.sleep(0.7)  # be a polite guest
    return resp.text


@dataclass
class ScrapeResult:
    entries: dict[int, dict] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    #: games whose page has no content yet because the matchup is still TBD
    pending: list[int] = field(default_factory=list)


def scrape(
    schedule: dict,
    *,
    only: int | None = None,
    refresh: bool = False,
) -> ScrapeResult:
    event_slug = schedule["tournament"]["fiba_event_slug"]
    schedule_games = schedule["games"]
    result = ScrapeResult()
    now = datetime.now(UTC).replace(microsecond=0).isoformat()

    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        listing = fetch(client, f"{BASE}/en/events/{event_slug}/games", refresh=refresh)
        games = extract_games(listing)
        if not games:
            raise RuntimeError(
                "No games array found in the listing payload -- FIBA's page structure "
                "has changed and scrape.py needs updating."
            )

        for game in games:
            number = match_number(game, schedule_games)
            if number is None:
                result.failures.append(f"unmatched FIBA game {game.get('gameName')}")
                continue
            if only is not None and number != only:
                continue

            url = game_page_url(game, event_slug)
            entry = {
                "fiba_game_id": game["gameId"],
                "fiba_game_name": game.get("gameName"),
                "url": clean_url(url),
                "venue": game.get("venueName"),
                "matchup_label": _matchup_label(game),
                "broadcasters": [],
                "scraped_at": now,
            }
            entry.update(_resolved_matchup(game))

            try:
                page = fetch(client, url, refresh=refresh)
                casters = extract_broadcasters(page)
            except Exception as exc:  # network, 404, redirect loop
                result.failures.append(f"game {number}: {exc}")
                casters = None

            if casters is None:
                # An unresolved bracket slot has no game page content yet -- FIBA
                # only publishes gameData once the matchup exists. That is expected,
                # not a parse failure, so it must not drown out real breakage.
                if _is_unresolved(game):
                    result.pending.append(number)
                else:
                    result.failures.append(f"game {number}: no broadcasters block on page")
                entry.pop("broadcasters")  # let the merge keep whatever we had before
            else:
                entry["broadcasters"] = clean_broadcasters(casters)

            result.entries[number] = entry

    return result


def _is_unresolved(game: dict) -> bool:
    """A bracket slot whose teams are not decided yet."""
    return not ((game.get("teamA") or {}).get("code") and (game.get("teamB") or {}).get("code"))


def _resolved_matchup(game: dict) -> dict:
    """Teams and tip-off, but only once FIBA has actually decided them.

    A bracket slot sits in the listing from day one with empty team codes and a
    22:00 UTC placeholder. Both facts flip together when the matchup is decided,
    so non-empty team codes are the signal that everything on the row is real.

    The time is still checked separately: 22:00 UTC is midnight in Berlin and no
    game tips then, so that value is a sentinel whatever the teams say.
    """
    if _is_unresolved(game):
        return {}

    out = {
        "home": (game.get("teamA") or {}).get("code"),
        "away": (game.get("teamB") or {}).get("code"),
    }
    raw = game.get("gameDateTimeUTC")
    if raw:
        try:
            tip = datetime.fromisoformat(raw).replace(tzinfo=UTC)
        except ValueError:
            return out
        if tip.hour != TBD_SENTINEL_HOUR or tip.minute != 0:
            out["tip_utc"] = tip.strftime("%Y-%m-%dT%H:%M")
    return out


def _matchup_label(game: dict) -> str | None:
    """FIBA's own wording for an unresolved game, e.g. '2nd of group A'."""
    a = (game.get("teamA") or {}).get("code") or game.get("teamAFrom")
    b = (game.get("teamB") or {}).get("code") or game.get("teamBFrom")
    return f"{a} - {b}" if a and b else None


def clean_broadcasters(casters: list[dict]) -> list[dict]:
    """Every broadcaster with the territories it holds rights in.

    Rights are per-territory: one game names 14-29 carriers across 200+
    countries. We keep the whole `countries` array rather than filtering to one
    viewer here, so a single scrape serves every country and the published page
    can let the reader pick their own. Filtering happens at render time.
    """
    out = []
    for b in casters:
        countries = sorted({str(c).upper() for c in (b.get("countries") or []) if c})
        if not countries:
            continue
        out.append({"name": b.get("name"), "url": clean_url(b.get("url")), "countries": countries})
    # Stable order, de-duplicated by (name, url).
    seen, deduped = {}, []
    for b in sorted(out, key=lambda b: (b["name"] or "").lower()):
        k = (b["name"], b["url"])
        if k in seen:
            # Same carrier listed twice: union the territories rather than drop one.
            merged = sorted(set(seen[k]["countries"]) | set(b["countries"]))
            seen[k]["countries"] = merged
            continue
        seen[k] = b
        deduped.append(b)
    return deduped


def broadcasters_for(casters: list[dict], viewer_country: str) -> list[dict]:
    """The subset holding rights in one country, as `{name, url}`."""
    want = viewer_country.upper()
    return [
        {"name": b["name"], "url": b["url"]}
        for b in casters
        if want in set(b.get("countries") or [])
    ]


# --------------------------------------------------------------------------- #
# merge + write
# --------------------------------------------------------------------------- #


def load_scraped() -> dict[int, dict]:
    if not SCRAPED_YAML.exists():
        return {}
    return yaml.safe_load(SCRAPED_YAML.read_text(encoding="utf-8")) or {}


def merge_and_write(result: ScrapeResult) -> dict[int, dict]:
    """Merge over the existing file. A game we failed to refresh keeps its data."""
    merged = load_scraped()
    for number, entry in result.entries.items():
        current = dict(merged.get(number) or {})
        current.update(entry)
        merged[number] = current

    ordered = {k: merged[k] for k in sorted(merged)}
    SCRAPED_YAML.write_text(
        "# GENERATED by `fiba-wwc scrape` -- do not hand-edit.\n"
        "# Merged, never overwritten: a game that fails to refresh keeps its last\n"
        "# good data. Committed on purpose so the site rebuilds offline and so\n"
        "# `git diff` after a scrape shows exactly what FIBA changed.\n"
        + yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return ordered
