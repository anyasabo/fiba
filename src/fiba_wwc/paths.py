"""Project paths. Everything is resolved relative to the repo root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
LOGOS = ASSETS / "logos"
DOCS = ROOT / "docs"
CACHE = ROOT / ".cache"
SOURCES = ROOT / "sources"  # hydrated by `fetch-sources`; gitignored

SCHEDULE_YAML = DATA / "schedule.yaml"
ROSTERS_YAML = DATA / "rosters.yaml"
WNBA_TEAMS_YAML = DATA / "wnba_teams.yaml"
SCRAPED_YAML = DATA / "fiba_scraped.yaml"
