"""Self-contained HTML: readable on screen, correct on a black-and-white printer.

Everything is inlined -- CSS and logo SVGs as data URIs -- so the page has zero
external requests, works offline, and prints identically to how it displays.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from .data import Game, Nation, Tournament
from .paths import LOGOS
from .render_markdown import PHASE_NAMES

_LOGO_CACHE: dict[str, str] = {}


def _logo_uri(abbr: str) -> str | None:
    """Base64 the club's SVG so the page carries its own images."""
    if abbr not in _LOGO_CACHE:
        path = LOGOS / f"{abbr}.svg"
        if not path.exists():
            _LOGO_CACHE[abbr] = ""
        else:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            _LOGO_CACHE[abbr] = f"data:image/svg+xml;base64,{data}"
    return _LOGO_CACHE[abbr] or None


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").replace(":00 ", " ").lower()


CSS = """
:root{
  --ink:#16181d; --muted:#5c626e; --faint:#8b91a0;
  --rule:#dcdfe6; --bg:#fff; --panel:#f6f7f9; --accent:#1a1c22;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
.wrap{max-width:920px;margin:0 auto;padding:32px 24px 64px}

header{border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:8px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.sub strong{color:var(--ink)}
.note{color:var(--faint);font-size:12px;margin-top:10px;max-width:60ch}

h2.day{font-size:15px;text-transform:uppercase;letter-spacing:.08em;
  margin:30px 0 0;padding:8px 0 6px;border-bottom:1px solid var(--rule)}

.game{padding:13px 0;border-bottom:1px solid var(--rule);
  display:grid;grid-template-columns:88px 1fr;gap:16px;
  break-inside:avoid;page-break-inside:avoid}
.time{font-weight:700;font-variant-numeric:tabular-nums;font-size:15px;padding-top:1px}
.time .tba{display:block;font-weight:400;font-size:10.5px;color:var(--faint);
  text-transform:uppercase;letter-spacing:.05em}
.title{font-size:16px;font-weight:650;margin:0 0 3px}
.title a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule)}
.meta{color:var(--muted);font-size:12px;margin-bottom:7px}
.meta .tag{display:inline-block;border:1px solid var(--rule);border-radius:3px;
  padding:0 5px;margin-right:6px;font-size:11px;color:var(--ink)}
.tbd{font-style:italic;color:var(--faint)}

.watch{font-size:12.5px;margin:0 0 8px;color:var(--muted)}
.watch b{color:var(--ink);font-weight:600}
.watch a{color:inherit}
.watch .none{color:var(--faint);font-style:italic}

.squad{margin:7px 0 0;padding:8px 10px;background:var(--panel);border-radius:5px}
.squad + .squad{margin-top:6px}
.nation{font-weight:650;font-size:13px;margin-bottom:5px}
.club{display:flex;align-items:center;gap:7px;font-size:12.5px;padding:2px 0}
.club img{width:17px;height:17px;object-fit:contain;flex:none}
.abbr{font-weight:700;font-size:10.5px;letter-spacing:.04em;
  border:1.5px solid var(--ink);border-radius:3px;padding:1px 4px;flex:none;min-width:34px;
  text-align:center}
.club .who{color:var(--muted)}
.club .who b{color:var(--ink);font-weight:600}
.unconf{color:var(--faint);font-style:italic}

.index{margin-top:44px;border-top:3px solid var(--ink);padding-top:18px}
.index h2{font-size:18px;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.card{border:1px solid var(--rule);border-radius:6px;padding:11px 13px;break-inside:avoid}
.card h3{display:flex;align-items:center;gap:8px;font-size:13.5px;margin:0 0 7px}
.card h3 img{width:22px;height:22px;object-fit:contain}
.card ul{margin:0;padding-left:15px;font-size:12.5px;color:var(--muted)}
.card li{margin:2px 0}
.card li b{color:var(--ink);font-weight:600}
.empty{color:var(--faint);font-size:12.5px;margin-top:14px}

footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--rule);
  color:var(--faint);font-size:11.5px}

@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    --ink:#e8eaee; --muted:#a2a9b8; --faint:#767d8c;
    --rule:#2c2f38; --bg:#14161a; --panel:#1c1f26;
  }
}

@media print{
  @page{margin:13mm}
  body{font-size:10.5pt;background:#fff;color:#000}
  .wrap{max-width:none;padding:0}
  /* Logos are the thing that survives greyscale, so force them to render. */
  img{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  a{text-decoration:none;color:#000}
  .note,footer{display:none}
  h2.day{break-after:avoid;page-break-after:avoid;margin-top:16px}
  .game{padding:8px 0;grid-template-columns:78px 1fr;gap:11px}
  .squad{background:none;border-left:2px solid #bbb;border-radius:0;padding:3px 0 3px 8px}
  .index{page-break-before:always}
  .grid{grid-template-columns:repeat(2,1fr)}
}
"""


def _club_rows(nation: Nation) -> str:
    by_club: dict = defaultdict(list)
    for p in nation.players:
        by_club[p.wnba.abbr].append(p)

    rows = []
    for abbr in sorted(by_club):
        players = by_club[abbr]
        club = players[0].wnba
        names = ", ".join(
            f"<b>{escape(p.name)}</b>"
            if p.confirmed
            else f'<span class="unconf">{escape(p.name)}</span>'
            for p in sorted(players, key=lambda p: (not p.confirmed, p.name))
        )
        uri = _logo_uri(abbr)
        img = f'<img src="{uri}" alt="">' if uri else ""
        rows.append(
            f'<div class="club">{img}'
            f'<span class="abbr">{abbr}</span>'
            f'<span class="who">{escape(club.name)} — {names}</span></div>'
        )
    return "".join(rows)


def _game_html(
    game: Game, tz: ZoneInfo, berlin: ZoneInfo, viewer_country: str, show_players: bool
) -> str:
    local = game.start_in(tz)
    if game.tip_utc is None:
        opts = " / ".join(_fmt_time(o.astimezone(tz)) for o in game.tip_options_utc)
        time_html = f'{opts}<span class="tba">slot TBA</span>'
    else:
        time_html = _fmt_time(local)

    title = escape(game.title())
    if game.url:
        title = f'<a href="{escape(game.url)}">{title}</a>'
    if not game.resolved:
        title += ' <span class="tbd">— matchup TBD</span>'

    tag = f"Group {game.group}" if game.group else PHASE_NAMES.get(game.phase, game.phase)
    meta = [
        f'<span class="tag">{escape(tag)}</span>',
        f"Berlin {game.start_in(berlin).strftime('%a %-d %b, %H:%M')}",
    ]
    if game.venue:
        meta.append(escape(game.venue))
    meta.append(f"Game {game.number}")

    if game.broadcasters:
        watch = " · ".join(
            f'<a href="{escape(b["url"])}">{escape(b["name"])}</a>'
            if b.get("url")
            else escape(b["name"])
            for b in game.broadcasters
        )
    else:
        watch = '<span class="none">not yet listed</span>'

    squads = ""
    if show_players:
        for nation in game.nations():
            if not nation.players:
                continue
            squads += (
                f'<div class="squad"><div class="nation">'
                f"{nation.flag} {escape(nation.name)}</div>{_club_rows(nation)}</div>"
            )

    return (
        f'<div class="game"><div class="time">{time_html}</div><div>'
        f'<div class="title">{title}</div>'
        f'<div class="meta">{" · ".join(meta)}</div>'
        f'<div class="watch"><b>Watch ({escape(viewer_country)}):</b> {watch}</div>'
        f"{squads}</div></div>"
    )


def _index_html(tournament: Tournament) -> str:
    by_club: dict = defaultdict(list)
    for nation in tournament.nations.values():
        for p in nation.players:
            by_club[p.wnba.abbr].append((p, nation))

    cards = []
    for abbr in sorted(by_club):
        club = tournament.wnba_teams[abbr]
        uri = _logo_uri(abbr)
        img = f'<img src="{uri}" alt="">' if uri else ""
        items = "".join(
            f"<li>{nation.flag} {escape(nation.name)} — "
            + (
                f"<b>{escape(p.name)}</b>"
                if p.confirmed
                else f'<span class="unconf">{escape(p.name)}</span>'
            )
            + "</li>"
            for p, nation in sorted(by_club[abbr], key=lambda x: (x[1].name, x[0].name))
        )
        cards.append(f'<div class="card"><h3>{img}{escape(club.name)}</h3><ul>{items}</ul></div>')

    missing = sorted(set(tournament.wnba_teams) - set(by_club))
    empty = ""
    if missing:
        names = ", ".join(tournament.wnba_teams[a].name for a in missing)
        empty = f'<p class="empty">No players in the tournament: {escape(names)}</p>'

    return (
        f'<section class="index"><h2>WNBA clubs at the World Cup</h2>'
        f'<div class="grid">{"".join(cards)}</div>{empty}</section>'
    )


def render(
    tournament: Tournament,
    tz: ZoneInfo,
    *,
    viewer_country: str = "US",
    show_players: bool = True,
    feed_url: str | None = None,
) -> str:
    berlin = tournament.local_tz
    by_day: dict = defaultdict(list)
    for g in tournament.games_in_order():
        by_day[g.start_in(tz).date()].append(g)

    body = []
    for day in sorted(by_day):
        body.append(f'<h2 class="day">{day.strftime("%A, %-d %B %Y")}</h2>')
        for g in by_day[day]:
            body.append(_game_html(g, tz, berlin, viewer_country, show_players))

    subscribe = ""
    if feed_url:
        subscribe = f' · <a href="{escape(feed_url)}">Subscribe to the calendar feed</a>'

    generated = datetime.now(UTC).strftime("%-d %B %Y, %H:%M UTC")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(tournament.name)}</title>
<style>{CSS}</style>
</head><body><div class="wrap">
<header>
  <h1>{escape(tournament.name)}</h1>
  <div class="sub">{escape(tournament.city)} · 4–13 September 2026 · all times
    <strong>{escape(tz.key)}</strong>{subscribe}</div>
  <p class="note">Games are grouped by your local day, which can differ from the
  Berlin match day — the Berlin date is on every game. Broadcast listings are the
  ones holding rights in {escape(viewer_country)}; rights differ by country.</p>
</header>
{"".join(body)}
{_index_html(tournament)}
<footer>Generated {generated} from the FIBA schedule and fiba.basketball.
Bold names are on confirmed rosters; italics are still in a preselect pool.</footer>
</div></body></html>
"""
