"""iCalendar feed.

Written by hand: the format is a few dozen lines of text and a library would be
more dependency than help.

The point of the feed is that it can be *subscribed to* rather than imported
once, so re-running the generator during the tournament updates events already
in someone's calendar. Two properties make that work:

  UID       stable per game and never reused, so a regenerated event replaces
            the existing one instead of appearing beside it.
  SEQUENCE  bumped only when something a subscriber would see actually changed
            (time, title, venue, broadcasters). A refresh that changes nothing
            must not bump it, or clients re-notify for no reason.

SEQUENCE is persisted in data/ics_state.yaml because it has to survive across
runs -- recomputing it from scratch would reset every event to 0.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import yaml

from .data import GAME_LENGTH, Game, Tournament
from .paths import DATA

STATE = DATA / "ics_state.yaml"
DOMAIN = "fiba-wwc.invalid"  # RFC 2606 reserved: UIDs must be unique, never resolved
PRODID = "-//fiba-wwc//FIBA Women's World Cup 2026//EN"


def _escape(text: str) -> str:
    """RFC 5545 text escaping: backslash, semicolon, comma, newline."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 caps lines at 75 octets; continuations start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        # 74 to leave room for the leading space on continuation lines
        if len(chunk) + len(b) > (75 if not out else 74):
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _uid(game: Game) -> str:
    return f"fiba-wwc-2026-game-{game.number}@{DOMAIN}"


def _summary(game: Game, tournament: Tournament) -> str:
    if game.resolved:
        base = f"{game.home.flag} {game.home.name} vs {game.away.name} {game.away.flag}"
    else:
        base = f"{game.label or f'Game {game.number}'} (TBD)"
    tag = f"Group {game.group}" if game.group else _phase(game)
    return f"🏀 {base} — {tag}"


def _phase(game: Game) -> str:
    return {
        "qualification": "Qualification to QF",
        "quarter_final": "Quarter-Final",
        "semi_final": "Semi-Final",
        "third_place": "3rd Place",
        "final": "Final",
    }.get(game.phase, game.phase)


def _description(game: Game, viewer_country: str) -> str:
    lines: list[str] = []

    if game.broadcasters:
        watch = ", ".join(
            f"{b['name']} ({b['url']})" if b.get("url") else b["name"] for b in game.broadcasters
        )
        lines.append(f"Watch ({viewer_country}): {watch}")
    else:
        lines.append(f"Watch ({viewer_country}): not yet listed")

    for nation in game.nations():
        if not nation.players:
            continue
        by_club: dict[str, list[str]] = {}
        for p in nation.players:
            label = p.name if p.confirmed else f"{p.name} (unconfirmed)"
            by_club.setdefault(p.wnba.name, []).append(label)
        lines.append("")
        lines.append(f"{nation.name} — WNBA players:")
        for club in sorted(by_club):
            lines.append(f"  {club}: {', '.join(sorted(by_club[club]))}")

    if game.tip_utc is None:
        lines.append("")
        lines.append(
            "Tip-off slot not yet assigned; this is the later of the two "
            "candidate slots and will move once FIBA confirms it."
        )
    if game.url:
        lines.append("")
        lines.append(game.url)
    return "\n".join(lines)


def _fingerprint(game: Game, summary: str, description: str) -> str:
    """What a subscriber would notice. Changes here, and only here, bump SEQUENCE."""
    payload = "|".join(
        [
            summary,
            _stamp(game.start_utc),
            game.venue or "",
            description,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load_state() -> dict:
    if not STATE.exists():
        return {}
    return yaml.safe_load(STATE.read_text(encoding="utf-8")) or {}


def _save_state(state: dict) -> None:
    STATE.write_text(
        "# GENERATED -- tracks iCalendar SEQUENCE numbers across runs.\n"
        "# SEQUENCE must increase when an event changes and stay put when it does\n"
        "# not, so subscribers see real updates and no spurious ones. Deleting this\n"
        "# file resets every event to SEQUENCE 0, which can make already-subscribed\n"
        "# calendars ignore later updates.\n"
        + yaml.safe_dump(state, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


def render(
    tournament: Tournament,
    *,
    viewer_country: str = "US",
    feed_url: str | None = None,
) -> str:
    state = _load_state()
    now = datetime.now(UTC)
    caldesc = (
        f"All {len(tournament.games)} games, with WNBA players "
        f"and {viewer_country} broadcast listings."
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(tournament.name)}",
        f"X-WR-CALDESC:{_escape(caldesc)}",
        "X-WR-TIMEZONE:UTC",
        # Hints only. Google ignores them; Apple Calendar honours them.
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    if feed_url:
        lines.append(f"SOURCE;VALUE=URI:{feed_url}")

    for game in tournament.games_in_order():
        uid = _uid(game)
        summary = _summary(game, tournament)
        description = _description(game, viewer_country)
        fingerprint = _fingerprint(game, summary, description)

        prior = state.get(uid) or {}
        sequence = int(prior.get("sequence", 0))
        if prior and prior.get("fingerprint") != fingerprint:
            sequence += 1
        state[uid] = {"sequence": sequence, "fingerprint": fingerprint}

        start = game.start_utc
        end = start + GAME_LENGTH

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            f"SEQUENCE:{sequence}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            f"STATUS:{'TENTATIVE' if game.tentative else 'CONFIRMED'}",
            "TRANSP:TRANSPARENT",
        ]
        location = ", ".join(x for x in (game.venue, tournament.city, "Germany") if x)
        lines.append(f"LOCATION:{_escape(location)}")
        if game.url:
            lines.append(f"URL:{game.url}")
        lines.append(f"CATEGORIES:{_escape('Basketball,FIBA Women World Cup 2026')}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    _save_state(state)
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
