"""Markdown schedule: games grouped by the reader's own local day."""

from __future__ import annotations

from collections import defaultdict
from zoneinfo import ZoneInfo

from .data import Game, Nation, Tournament

PHASE_NAMES = {
    "group": "Group Phase",
    "qualification": "Qualification to Quarter-Finals",
    "quarter_final": "Quarter-Finals",
    "semi_final": "Semi-Finals",
    "third_place": "3rd Place Game",
    "final": "Final",
}


def _fmt_time(dt) -> str:
    return dt.strftime("%-I:%M %p").lower().replace(":00 ", " ")


def _logo(abbr: str, depth: int) -> str:
    """Inline logo image, path relative to the generated file in docs/."""
    return f"![{abbr}]({'../' * depth}assets/logos/{abbr}.svg)"


def _nation_lines(n: Nation, depth: int) -> list[str]:
    """One row per WNBA club, not per player."""
    if not n.players:
        return []
    by_club: dict[str, list] = defaultdict(list)
    for p in n.players:
        by_club[p.wnba.abbr].append(p)

    lines = []
    for abbr in sorted(by_club):
        players = by_club[abbr]
        club = players[0].wnba
        names = ", ".join(
            p.name if p.confirmed else f"{p.name} _(unconfirmed)_"
            for p in sorted(players, key=lambda p: (not p.confirmed, p.name))
        )
        lines.append(f"    - **{abbr}** {_logo(abbr, depth)} {club.name} — {names}")
    return lines


def _watch_line(game: Game, viewer_country: str) -> str:
    if not game.broadcasters:
        return f"  - 📺 Watch ({viewer_country}): _not yet listed_"
    parts = []
    for b in game.broadcasters:
        name = b.get("name") or "?"
        url = b.get("url")
        parts.append(f"[{name}]({url})" if url else name)
    return f"  - 📺 Watch ({viewer_country}): " + " · ".join(parts)


def render(
    tournament: Tournament,
    tz: ZoneInfo,
    *,
    viewer_country: str = "US",
    show_players: bool = True,
    logo_depth: int = 1,
) -> str:
    tzname = tz.key
    berlin = tournament.local_tz

    by_day: dict = defaultdict(list)
    for g in tournament.games_in_order():
        by_day[g.start_in(tz).date()].append(g)

    out: list[str] = [
        f"# {tournament.name}",
        "",
        f"{tournament.city} · 4–13 September 2026 · all times **{tzname}**",
        "",
        "Games are grouped by *your* local day, which can differ from the Berlin "
        "match day — the Berlin date is shown on each game.",
        "",
    ]

    for day in sorted(by_day):
        out.append(f"## {day.strftime('%A, %B %-d, %Y')}")
        out.append("")
        for g in by_day[day]:
            local = g.start_in(tz)
            berlin_dt = g.start_in(berlin)

            when = _fmt_time(local)
            if g.tip_utc is None:
                others = " or ".join(_fmt_time(o.astimezone(tz)) for o in g.tip_options_utc)
                when = f"{others} (slot TBA)"

            tag = f"Group {g.group}" if g.group else PHASE_NAMES.get(g.phase, g.phase)
            title = g.title()
            if g.url:
                title = f"[{title}]({g.url})"

            head = f"- **{when}** — {title}  ·  {tag} · Game {g.number}"
            if not g.resolved:
                head += " · _matchup TBD_"
            out.append(head)

            meta = [f"Berlin: {berlin_dt.strftime('%a %-d %b, %H:%M')}"]
            if g.venue:
                meta.append(g.venue)
            out.append(f"  - 🏟 {' · '.join(meta)}")
            out.append(_watch_line(g, viewer_country))

            if show_players:
                for n in g.nations():
                    lines = _nation_lines(n, logo_depth)
                    if lines:
                        out.append(f"  - {n.flag} **{n.name}** — WNBA players:")
                        out.extend(lines)
            out.append("")
        out.append("")

    out.extend(_wnba_index(tournament, logo_depth))
    return "\n".join(out).rstrip() + "\n"


def _wnba_index(tournament: Tournament, logo_depth: int = 1) -> list[str]:
    """Reverse view: which national team is each WNBA club represented on."""
    by_club: dict = defaultdict(list)
    for nation in tournament.nations.values():
        for p in nation.players:
            by_club[p.wnba.abbr].append((p, nation))

    out = ["## WNBA clubs at the World Cup", ""]
    for abbr in sorted(by_club):
        club = tournament.wnba_teams[abbr]
        out.append(f"### {_logo(abbr, logo_depth)} {club.name} ({abbr})")
        out.append("")
        for p, nation in sorted(by_club[abbr], key=lambda x: (x[1].name, x[0].name)):
            mark = "" if p.confirmed else " _(unconfirmed)_"
            out.append(f"- {nation.flag} {nation.name} — {p.name}{mark}")
        out.append("")

    missing = sorted(set(tournament.wnba_teams) - set(by_club))
    if missing:
        names = ", ".join(tournament.wnba_teams[a].name for a in missing)
        out.append(f"_No players in the tournament:_ {names}")
        out.append("")
    return out
