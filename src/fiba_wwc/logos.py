"""Download WNBA club logos once into assets/logos/.

Committed to the repo so rendering is offline and the published page has no
third-party dependency. SVG only: the HTML build base64-inlines it and the
Markdown build links to it, and both stay crisp at any size.
"""

from __future__ import annotations

import httpx
import yaml

from .paths import LOGOS, WNBA_TEAMS_YAML

CDN = "https://cdn.wnba.com/logos/wnba/{logo_id}/primary/L/logo.svg"


def fetch_all(*, refresh: bool = False) -> tuple[int, list[str]]:
    teams = yaml.safe_load(WNBA_TEAMS_YAML.read_text(encoding="utf-8"))
    LOGOS.mkdir(parents=True, exist_ok=True)
    fetched, misses = 0, []

    with httpx.Client(
        timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    ) as client:
        for abbr, spec in teams.items():
            path = LOGOS / f"{abbr}.svg"
            if path.exists() and not refresh:
                continue
            url = CDN.format(logo_id=spec["logo_id"])
            try:
                r = client.get(url)
                r.raise_for_status()
                # The CDN answers 200 with a tiny error document for unknown
                # ids, so size is the real signal that we got a logo.
                if len(r.content) < 500:
                    raise ValueError(f"suspiciously small ({len(r.content)} bytes)")
            except Exception as exc:
                misses.append(f"{abbr}.svg: {exc}")
                continue
            path.write_bytes(r.content)
            fetched += 1

    return fetched, misses
