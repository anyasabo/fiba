"""Self-contained HTML: readable on screen, correct on a black-and-white printer.

Everything is inlined -- CSS and logo SVGs as data URIs -- so the page has zero
external requests, works offline, and prints identically to how it displays.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo

from .data import Game, Nation, Tournament
from .paths import LOGOS
from .render_markdown import PHASE_NAMES

_LOGO_CACHE: dict[str, str] = {}

# A basketball drawn as an emoji inside an SVG, base64'd into the <link> so the
# page still makes zero external requests. Rendered by whatever emoji font the
# reader's system has; the dy nudge centres it in the glyph box.
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<text y="26" font-size="28">\N{BASKETBALL AND HOOP}</text></svg>'
)
FAVICON_URI = "data:image/svg+xml;base64," + base64.b64encode(_FAVICON_SVG.encode("utf-8")).decode(
    "ascii"
)


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
/* Contrast against --bg and against --panel, which faint text also sits on:
   ink 17.8, muted 6.1, faint 4.8, link 6.7 -- all clear WCAG AA's 4.5 for body
   text. --faint was #8b91a0 (3.2) and links were the browser default, which is
   1.9 against the dark background. Both failed, and unconfirmed player names
   are faint -- that is content, not decoration. */
:root{
  --ink:#16181d; --muted:#5c626e; --faint:#6b7280; --link:#0b5cad;
  --rule:#dcdfe6; --bg:#fff; --panel:#f6f7f9; --accent:#1a1c22;
}
a{color:var(--link)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
.wrap{max-width:920px;margin:0 auto;padding:32px 24px 64px}

header{border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:8px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.sub strong{color:var(--ink)}
.sub .hint{color:var(--faint)}
.note{color:var(--faint);font-size:12px;margin-top:10px;max-width:60ch}
.controls{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px;font-size:12px;
  color:var(--muted)}
.controls label{display:flex;align-items:center;gap:6px}
.controls select{font:inherit;font-size:12px;color:var(--ink);background:var(--bg);
  border:1px solid var(--rule);border-radius:4px;padding:3px 5px;max-width:15rem}

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
.meta .tag,.card h3 .tag{display:inline-block;border:1px solid var(--rule);
  border-radius:3px;padding:0 5px;font-size:11px;color:var(--ink);font-weight:400}
.meta .tag{margin-right:6px}
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
.card h3 .cnt{margin-left:auto;font-weight:400;font-size:11px;color:var(--faint);
  white-space:nowrap}
.card .club{padding:3px 0}
.card h3 img{width:22px;height:22px;object-fit:contain}
.card ul{margin:0;padding-left:15px;font-size:12.5px;color:var(--muted)}
.card li{margin:2px 0}
.card li b{color:var(--ink);font-weight:600}
.empty{color:var(--faint);font-size:12.5px;margin-top:14px}

footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--rule);
  color:var(--faint);font-size:11.5px}

@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    /* ink 15.0, muted 7.7, faint 5.4, link 8.6 against --bg. */
    --ink:#e8eaee; --muted:#a2a9b8; --faint:#868d9d; --link:#8ab4f8;
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
  .note,footer,.controls{display:none}
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

    casters = game.broadcasters_in(viewer_country)
    if casters:
        watch = " · ".join(
            f'<a href="{escape(b["url"])}">{escape(b["name"])}</a>'
            if b.get("url")
            else escape(b["name"])
            for b in casters
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

    # data-* carries the UTC facts the client needs to re-render in another zone.
    # Order never changes -- games are sorted on an absolute instant -- so only the
    # time labels and the day headings between them have to move.
    opts = ",".join(_iso(o) for o in game.tip_options_utc)
    return (
        f'<div class="game" data-game="{game.number}" data-utc="{_iso(game.start_utc)}"'
        f"{f' data-opts="{opts}"' if game.tip_utc is None else ''}>"
        f'<div class="time">{time_html}</div><div>'
        f'<div class="title">{title}</div>'
        f'<div class="meta">{" · ".join(meta)}</div>'
        f'<div class="watch"><b>Watch (<span class="cc">{escape(viewer_country)}</span>):</b> '
        f'<span class="out">{watch}</span></div>'
        f"{squads}</div></div>"
    )


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _nations_html(tournament: Tournament) -> str:
    """The mirror of _index_html: each national team and its WNBA players."""
    with_players = [n for n in tournament.nations.values() if n.players]
    with_players.sort(key=lambda n: (n.group or "", n.name))

    cards = []
    for nation in with_players:
        total = len(nation.players)
        unconfirmed = sum(1 for p in nation.players if not p.confirmed)
        count = f"{total} player{'s' if total != 1 else ''}"
        if unconfirmed:
            count += f", {unconfirmed} unconfirmed"
        group = f'<span class="tag">Group {escape(nation.group)}</span>' if nation.group else ""

        rows = ""
        for p in sorted(nation.players, key=lambda p: (not p.confirmed, p.name)):
            uri = _logo_uri(p.wnba.abbr)
            img = f'<img src="{uri}" alt="">' if uri else ""
            who = (
                f"<b>{escape(p.name)}</b>"
                if p.confirmed
                else f'<span class="unconf">{escape(p.name)}</span>'
            )
            rows += (
                f'<div class="club">{img}<span class="abbr">{p.wnba.abbr}</span>'
                f'<span class="who">{who} — {escape(p.wnba.name)}</span></div>'
            )
        cards.append(
            f'<div class="card"><h3>{nation.flag} {escape(nation.name)} {group}'
            f'<span class="cnt">{count}</span></h3>{rows}</div>'
        )

    none = sorted((n for n in tournament.nations.values() if not n.players), key=lambda n: n.name)
    empty = ""
    if none:
        names = ", ".join(f"{n.flag} {n.name}" for n in none)
        empty = f'<p class="empty">No WNBA players: {escape(names)}</p>'

    return (
        f'<section class="index"><h2>National teams and their WNBA players</h2>'
        f'<div class="grid">{"".join(cards)}</div>{empty}</section>'
    )


def _payload(tournament: Tournament) -> str:
    """The UTC facts and the full broadcaster table, for client-side re-rendering.

    Carrying every territory costs ~60KB of JSON, which brotli squeezes to a few
    KB and buys a page that answers "how do I watch this" for any country instead
    of only the one it was built for. Broadcaster names and URLs are deduplicated
    into a table because 24 games share 49 carriers between them.
    """
    table: dict[tuple[str, str], int] = {}
    per_game: dict[int, list] = {}
    for game in tournament.games:
        rows = []
        for b in game.broadcasters:
            key = (b.get("name") or "", b.get("url") or "")
            idx = table.setdefault(key, len(table))
            rows.append([idx, b.get("countries") or []])
        if rows:
            per_game[game.number] = rows

    countries = sorted({c for rows in per_game.values() for _, cs in rows for c in cs})
    casters = [list(k) for k, _ in sorted(table.items(), key=lambda kv: kv[1])]
    return json.dumps(
        {
            "casters": casters,
            "games": per_game,
            "countries": countries,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


CONTROLS = """
<div class="controls" hidden>
  <label>Time zone <select id="tz"></select></label>
  <label>Watch from <select id="cc"></select></label>
</div>
"""

SCRIPT = r"""
(function () {
  var D = window.__FIBA__, root = document.getElementById('schedule');
  if (!D || !root) return;
  var games = [].slice.call(root.querySelectorAll('.game'));
  var tzSel = document.getElementById('tz'), ccSel = document.getElementById('cc');

  // Without Intl support the server-rendered Pacific/US page is still correct,
  // so leave it alone rather than degrading it.
  try { new Intl.DateTimeFormat('en', { timeZone: 'UTC' }); } catch (e) { return; }

  function opt(sel, value, label, chosen) {
    var o = document.createElement('option');
    o.value = value; o.textContent = label; if (value === chosen) o.selected = true;
    sel.appendChild(o);
  }

  var COMMON = ['America/Los_Angeles','America/Denver','America/Chicago','America/New_York',
                'America/Toronto','Europe/London','Europe/Paris','Europe/Berlin','Europe/Madrid',
                'Europe/Rome','Europe/Budapest','Europe/Istanbul','Africa/Lagos','Africa/Bamako',
                'Asia/Shanghai','Asia/Seoul','Asia/Tokyo','Australia/Sydney','UTC'];
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem('fiba-view') || '{}'); } catch (e) {}
  var tz = saved.tz || D.tz, cc = saved.cc || D.cc;

  var all = [];
  try { all = Intl.supportedValuesOf('timeZone'); } catch (e) {}
  var here = '';
  try { here = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
  var list = COMMON.slice();
  [here, tz].forEach(function (z) { if (z && list.indexOf(z) < 0) list.unshift(z); });
  all.forEach(function (z) { if (list.indexOf(z) < 0) list.push(z); });
  list.forEach(function (z) { opt(tzSel, z, z.replace(/_/g, ' '), tz); });

  var names = null;
  try { names = new Intl.DisplayNames(['en'], { type: 'region' }); } catch (e) {}
  var label = function (c) { try { return (names && names.of(c)) || c; } catch (e) { return c; } };
  D.countries.slice().sort(function (a, b) { return label(a).localeCompare(label(b)); })
    .forEach(function (c) { opt(ccSel, c, label(c), cc); });

  var fmtTime = function (d, z) {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: z, hour: 'numeric', minute: '2-digit'
    }).format(d).replace(':00 ', ' ').toLowerCase();
  };
  var fmtDay = function (d, z) {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: z, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
    }).format(d);
  };
  var dayKey = function (d, z) {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: z, year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(d);
  };

  function apply() {
    // Times, and the day headings between them. Game order is fixed: it is a sort
    // on an absolute instant, so only the boundaries move between zones.
    [].slice.call(root.querySelectorAll('h2.day')).forEach(function (h) { h.remove(); });
    var prev = null;
    games.forEach(function (el) {
      var start = new Date(el.getAttribute('data-utc'));
      var key = dayKey(start, tz);
      if (key !== prev) {
        var h = document.createElement('h2');
        h.className = 'day';
        h.textContent = fmtDay(start, tz);
        el.parentNode.insertBefore(h, el);
        prev = key;
      }
      var opts = el.getAttribute('data-opts');
      var slot = el.querySelector('.time');
      if (opts) {
        slot.innerHTML = opts.split(',').map(function (o) {
          return fmtTime(new Date(o), tz);
        }).join(' / ') + '<span class="tba">slot TBA</span>';
      } else {
        slot.textContent = fmtTime(start, tz);
      }

      var rows = D.games[el.getAttribute('data-game')] || [];
      var mine = rows.filter(function (r) { return r[1].indexOf(cc) >= 0; })
        .map(function (r) { return D.casters[r[0]]; })
        .sort(function (a, b) { return a[0].toLowerCase().localeCompare(b[0].toLowerCase()); });
      var watch = el.querySelector('.watch');
      watch.querySelector('.cc').textContent = cc;
      var out = watch.querySelector('.out');
      if (!mine.length) {
        out.innerHTML = '<span class="none">not yet listed</span>';
      } else {
        out.innerHTML = mine.map(function (b) {
          var name = b[0].replace(/[&<>]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
          });
          var href = b[1].replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
          });
          return b[1] ? '<a href="' + href + '">' + name + '</a>' : name;
        }).join(' · ');
      }
    });
    var lab = document.getElementById('tzlabel');
    if (lab) lab.textContent = tz;
    try { localStorage.setItem('fiba-view', JSON.stringify({ tz: tz, cc: cc })); } catch (e) {}
  }

  tzSel.addEventListener('change', function () { tz = tzSel.value; apply(); });
  ccSel.addEventListener('change', function () { cc = ccSel.value; apply(); });
  document.querySelector('.controls').hidden = false;
  if (tz !== D.tz || cc !== D.cc) apply();
})();
"""


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
        # The feed's times are UTC-anchored so they land correctly in any
        # calendar, but its broadcaster lines are fixed to whichever country the
        # page was built for -- the country dropdown does not reach into it.
        subscribe = (
            f' · <a href="{escape(feed_url)}">Subscribe to the calendar feed</a>'
            f' <span class="hint">(times suit any calendar; its listings are'
            f" {escape(viewer_country.upper())} only)</span>"
        )

    generated = datetime.now(UTC).strftime("%-d %B %Y, %H:%M UTC")
    payload = _payload(tournament)
    tzkey = json.dumps(tz.key)
    cc = json.dumps(viewer_country.upper())

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(tournament.name)}</title>
<link rel="icon" href="{FAVICON_URI}">
<style>{CSS}</style>
</head><body><div class="wrap">
<header>
  <h1>{escape(tournament.name)}</h1>
  <div class="sub">{escape(tournament.city)} · 4–13 September 2026 · all times
    <strong id="tzlabel">{escape(tz.key)}</strong>{subscribe}</div>
  <p class="note">Games are grouped by your local day, which can differ from the
  Berlin match day — the Berlin date is on every game. Broadcast listings are the
  ones holding rights in the country you pick; rights differ by country.</p>
  {CONTROLS}
</header>
<div id="schedule">{"".join(body)}</div>
{_nations_html(tournament)}
{_index_html(tournament)}
<footer>Generated {generated} from the FIBA schedule and fiba.basketball.
Bold names are on confirmed rosters; italics are still in a preselect pool.</footer>
</div>
<script>window.__FIBA__={payload};Object.assign(window.__FIBA__,{{tz:{tzkey},cc:{cc}}});</script>
<script>{SCRIPT}</script>
</body></html>
"""
