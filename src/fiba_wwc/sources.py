"""Re-download the upstream documents the hand-edited data was transcribed from.

These are third-party material -- FIBA's schedule PDF and a magazine article --
so they are not committed. They are provenance, not inputs: nothing in the
build reads them. Run this when you need to re-check a transcription against
what it came from.

    uv run fiba-wwc fetch-sources
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .paths import SOURCES


@dataclass(frozen=True)
class Source:
    filename: str
    url: str
    note: str


SOURCES_LIST = (
    Source(
        "fiba-schedule.pdf",
        "https://assets.fiba.basketball/image/upload/"
        "fiba-womens-basketball-world-cup-208875-game-schedule.pdf",
        "official schedule; every date and tip-off in data/schedule.yaml came from it",
    ),
    Source(
        "wnba-players.html",
        "https://highposthoops.com/"
        "every-wnba-player-who-will-play-in-the-2026-fiba-world-cup-in-berlin",
        "High Post Hoops, 7 Aug 2026; data/rosters.yaml was first transcribed from it",
    ),
    Source(
        "wnba-rosters.html",
        "https://www.wnba.com/news/2026-fiba-womens-basketball-world-cup-wnba-rosters",
        "WNBA.com's own list as of 3 Sep 2026, 51 current and 19 former players; "
        "data/rosters.yaml was reconciled against it and it is the source for the "
        "developmental players FIBA lists at a European club",
    ),
)


def fetch_all(*, refresh: bool = False) -> tuple[int, list[str]]:
    SOURCES.mkdir(parents=True, exist_ok=True)
    fetched, misses = 0, []

    with httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    ) as client:
        for source in SOURCES_LIST:
            path = SOURCES / source.filename
            if path.exists() and not refresh:
                continue
            try:
                r = client.get(source.url)
                r.raise_for_status()
            except Exception as exc:
                misses.append(f"{source.filename}: {exc}")
                continue
            path.write_bytes(r.content)
            fetched += 1

    return fetched, misses
