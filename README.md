# FIBA Women's Basketball World Cup 2026

Berlin, 4–13 September 2026. Stores the schedule, the WNBA players on each
national team, and the US broadcast listings once — then renders whatever view
is needed from that one set of data.

```sh
uv run fiba-wwc generate          # docs/{schedule.md,index.html,fiba.ics}, Pacific time
uv run fiba-wwc scrape            # refresh links + broadcasters from fiba.basketball
uv run fiba-wwc fetch-logos       # download WNBA club logos (once)
uv run fiba-wwc fetch-sources     # re-download the upstream PDF + article into sources/
uv run fiba-wwc check             # validate the data files against each other
```

Python 3.14, managed with [uv](https://docs.astral.sh/uv/). `uv run ruff check`
and `uv run ruff format` lint and format the whole tree.

Three outputs, all from the same data:

- `docs/schedule.md` — markdown, one row per WNBA club with its logo (linked
  from `assets/logos/`, so read it inside the repo rather than on Pages)
- `docs/index.html` — self-contained page; the GitHub Pages front page and the
  thing you print (its `@media print` block is greyscale-safe)
- `docs/fiba.ics` — subscribable calendar feed

`docs/.nojekyll` keeps Pages from running the directory through Jekyll: the
site is `index.html` plus the feed, and the markdown is a repo-reading artifact.

## Data

Three files are **hand-edited** — they are the source of truth:

| file | what it holds |
|---|---|
| `data/schedule.yaml` | 36 games. Times stored as **UTC**; every display timezone is derived. |
| `data/rosters.yaml` | WNBA players by national team, `confirmed` / `unconfirmed`. |
| `data/wnba_teams.yaml` | The 15 WNBA clubs, colours, and CDN logo ids. |

One file is **generated** and committed:

| file | what it holds |
|---|---|
| `data/fiba_scraped.yaml` | Official game URLs, venues, and broadcast listings. |

Committing the scraped file means the site rebuilds offline, and `git diff`
after a scrape shows exactly what FIBA changed.

### Where the hand-edited data came from

`data/schedule.yaml` was transcribed from FIBA's official schedule PDF;
`data/rosters.yaml` from a High Post Hoops article of 7 Aug 2026. Both are
third-party documents and neither is committed — they are provenance, not build
inputs, and nothing in the build reads them. `uv run fiba-wwc fetch-sources`
re-downloads both into `sources/` (gitignored) when a transcription needs
re-checking.

## Updating during the tournament

**A knockout matchup is decided.** Edit that game in `data/schedule.yaml`: set
`home` and `away`, and replace `tip_utc_options: [...]` with a single `tip_utc`.
Then re-run `scrape` and `generate`.

```yaml
- {number: 25, phase: qualification, label: "2nd A - 3rd B",
   date_utc: 2026-09-08, tip_utc: "18:45", home: FRA, away: JPN}
```

**A national roster is finalised.** Flip a player's `status` to `confirmed` in
`data/rosters.yaml`, or add a line. `--confirmed-only` hides everything still
speculative.

**Broadcast listings appear.** Just `uv run fiba-wwc scrape`. FIBA only publishes
a game page once the matchup exists, so the 12 knockout games report as "still
TBD" until then — that is expected, not an error.

## Broadcast listings are per-country

Rights differ by territory: a single game page lists ~17 broadcasters covering
100+ countries. The scraper filters on the broadcaster's rights list, so the
question it answers is *"how do I watch this from the US"* — for **all 36 games**,
not just Team USA's.

```sh
uv run fiba-wwc scrape --viewer-country FR
```

For Hungary–France, that difference is real: US viewers get Courtside 1891 and
TNT; French viewers get Courtside 1891, beIN Sports 1 and TFX.

Tracking and referral params (`utm_*`, `fbclid`, `ref`, …) are stripped from
every URL before it is stored or rendered.

## How the scrape works, and how it breaks

fiba.basketball is a Next.js app that renders client-side but ships its data as
a React flight payload inside `self.__next_f.push([1,"<json>"])`. `scrape.py`
concatenates those chunks and pulls values out by key. This is undocumented and
**will** break when FIBA redesigns. Three containment measures:

- all parsing lives in `scrape.py`; nothing else in the project knows about it
- results are **merged**, never overwritten — a game that fails to refresh keeps
  its last good data, and the run only fails outright if *nothing* parsed
- pages are cached under `.cache/`, so iterating on the parser costs no requests
  (`--refresh` to bypass)

`fiba-wwc check` cross-checks all 24 hand-transcribed group tip-offs against
FIBA's own `gameDateTimeUTC`, which is what caught that the tournament has 36
games rather than the 40 initially assumed.

## Calendar subscription, and how fast it updates

Publish `docs/` to GitHub Pages, then in Google Calendar use
**Other calendars → + → From URL** with `https://<user>.github.io/<repo>/fiba.ics`.
That subscribes rather than imports, so re-running the generator updates events
already in the calendar instead of duplicating them. Two things make that work:

- **`UID`** is stable per game (`fiba-wwc-2026-game-25@fiba-wwc.invalid`) and
  never reused, so a regenerated event replaces its predecessor. The domain half
  is only there for uniqueness — nothing resolves it, so it uses the `.invalid`
  TLD reserved by RFC 2606.
- **`SEQUENCE`** is bumped *only* when something a subscriber would notice
  changed — time, title, venue, broadcasters. It is persisted in
  `data/ics_state.yaml` because it has to survive across runs. Do not delete
  that file: resetting every event to `SEQUENCE 0` can make already-subscribed
  calendars ignore later updates.

**The catch is latency.** Google polls external `.ics` URLs on its own schedule
— typically several hours, sometimes up to a day — and ignores the
`REFRESH-INTERVAL` and `X-PUBLISHED-TTL` hints the feed sets. There is no way to
force a refresh short of removing and re-adding the calendar. So the feed is
right for sharing and for roster/broadcast updates, but do not expect a
quarter-final matchup to appear in Google within the hour.

Apple Calendar honours the refresh hints and lets you set the interval per
subscription (down to every 5 minutes), so it reflects changes far sooner.

For near-instant updates in *your own* Google Calendar, the reliable route is
the Google Calendar API — writing events directly instead of publishing a feed.
That needs an OAuth client and is not built here.
