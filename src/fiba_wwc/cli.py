"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from . import checks, data, render_html, render_ics, render_markdown
from . import logos as logos_mod
from . import scrape as scrape_mod
from . import sources as sources_mod
from .paths import DOCS, SCHEDULE_YAML

DEFAULT_TZ = "America/Los_Angeles"


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"unknown timezone: {name}") from exc


def cmd_scrape(args) -> int:
    schedule = yaml.safe_load(SCHEDULE_YAML.read_text(encoding="utf-8"))
    result = scrape_mod.scrape(
        schedule,
        viewer_country=args.viewer_country,
        only=args.game,
        refresh=args.refresh,
    )
    merged = scrape_mod.merge_and_write(result)

    print(f"refreshed {len(result.entries)} games; {len(merged)} total on file")
    with_casters = sum(1 for e in merged.values() if e.get("broadcasters"))
    print(f"{with_casters} games have {args.viewer_country} broadcast listings")
    if result.pending:
        nums = ", ".join(str(n) for n in sorted(result.pending))
        print(f"{len(result.pending)} games still TBD (no page yet): {nums}")
    for f in result.failures:
        print(f"  warning: {f}", file=sys.stderr)
    if not result.entries:
        print("nothing parsed at all -- the page structure has moved", file=sys.stderr)
        return 1
    return 0


def cmd_fetch_logos(args) -> int:
    fetched, misses = logos_mod.fetch_all(refresh=args.refresh)
    print(f"downloaded {fetched} logo files")
    for m in misses:
        print(f"  missing: {m}", file=sys.stderr)
    return 0


def cmd_fetch_sources(args) -> int:
    fetched, misses = sources_mod.fetch_all(refresh=args.refresh)
    print(f"downloaded {fetched} source documents into sources/")
    for m in misses:
        print(f"  missing: {m}", file=sys.stderr)
    return 1 if misses else 0


def cmd_generate(args) -> int:
    tz = _tz(args.tz)
    tournament = data.load(include_unconfirmed=not args.confirmed_only)

    DOCS.mkdir(exist_ok=True)
    want = {"markdown", "html", "ics"} if args.format == "all" else {args.format}
    feed_url = f"{args.base_url.rstrip('/')}/fiba.ics" if args.base_url else None

    if "markdown" in want:
        text = render_markdown.render(
            tournament,
            tz,
            viewer_country=args.viewer_country,
            show_players=not args.no_players,
        )
        _write(DOCS / "schedule.md", text)

    if "html" in want:
        html = render_html.render(
            tournament,
            tz,
            viewer_country=args.viewer_country,
            show_players=not args.no_players,
            feed_url=feed_url,
        )
        _write(DOCS / "index.html", html)

    if "ics" in want:
        ics = render_ics.render(
            tournament,
            viewer_country=args.viewer_country,
            feed_url=feed_url,
        )
        _write(DOCS / "fiba.ics", ics)
        if not feed_url:
            print("  note: pass --base-url to embed the subscribe URL in the feed")

    return 0


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(
        f"wrote {path.parent.name}/{path.name} "
        f"({len(text.splitlines())} lines, {len(text.encode()):,} bytes)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fiba-wwc",
        description="Schedule, rosters and US broadcast listings for the "
        "FIBA Women's Basketball World Cup 2026.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scrape", help="refresh official links and broadcast listings")
    s.add_argument(
        "--viewer-country",
        default="US",
        help="ISO country code of the VIEWER; broadcasters are filtered to "
        "those holding rights there (default: US)",
    )
    s.add_argument("--game", type=int, help="refresh only this game number")
    s.add_argument("--refresh", action="store_true", help="bypass the .cache/ of downloaded pages")
    s.set_defaults(func=cmd_scrape)

    g = sub.add_parser("generate", help="render the schedule")
    g.add_argument("--tz", default=DEFAULT_TZ, help=f"IANA timezone (default: {DEFAULT_TZ})")
    g.add_argument("--viewer-country", default="US")
    g.add_argument(
        "--confirmed-only",
        action="store_true",
        help="hide players who are only in a preselect pool",
    )
    g.add_argument("--no-players", action="store_true")
    g.add_argument("--format", default="all", choices=["all", "markdown", "html", "ics"])
    g.add_argument(
        "--base-url",
        default="https://anyasabo.github.io/fiba",
        help="public base URL of docs/, used to build the calendar "
        "subscribe link (pass empty to omit)",
    )
    g.set_defaults(func=cmd_generate)

    fl = sub.add_parser("fetch-logos", help="download WNBA club logos into assets/logos/")
    fl.add_argument("--refresh", action="store_true", help="re-download logos already on disk")
    fl.set_defaults(func=cmd_fetch_logos)

    fs = sub.add_parser(
        "fetch-sources", help="re-download the upstream PDF and article into sources/"
    )
    fs.add_argument("--refresh", action="store_true", help="re-download files already on disk")
    fs.set_defaults(func=cmd_fetch_sources)

    c = sub.add_parser("check", help="validate the data files against each other and FIBA")
    c.set_defaults(func=lambda a: checks.run_all())

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
