# FIBA Women's Basketball World Cup 2026 Schedule

As a mostly WNBA fan in the USA who wanted to watch the FIBA World Cup games, I wanted to be able to know

* which WNBA players are on which teams?
* which games are those players in?
* what time are those games, and how can I watch them?

and no one source had that information easily available. So a few tokens later this exists to glue that information together. The output is in the `docs/` dir, generated from the `data/` dir.

The scripts can run against your own time zone or your own viewing country, and can be re-run as national teams get confirmed and as the tournament progresses so the teams are locked in.

Multiple games have potential time slots today that are not fully locked in.

This was entirely clanker generated. I would not recommend reading it with your own eyes. Go watch the Leite show instead.

## clanker-generated below

Berlin, 4–13 September 2026. Stores the schedule, the WNBA players on each
national team, and the US broadcast listings once — then renders whatever view
is needed from that one set of data.

```sh
uv run fiba-wwc generate          # docs/{schedule.md,index.html,fiba.ics}, Pacific time
uv run fiba-wwc scrape            # refresh links + broadcasters from fiba.basketball
uv run fiba-wwc scrape-rosters    # refresh national squads from FIBA's roster tracker
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
| `data/fiba_rosters.yaml` | The 16 national squads as FIBA's roster tracker publishes them. |

Committing the scraped files means the site rebuilds offline, and `git diff`
after a scrape shows exactly what FIBA changed — which is the whole point of
`scrape-rosters`: when a federation cuts its pool of 23 down to a final 12, the
diff says so.

### What the roster tracker can and cannot settle

It is the official source for *which names a federation has published*, and it
carries FIBA's own disclaimer that these "do not necessarily correspond to the
rosters that will play". So it does **not** decide `status`. A federation can
confirm an individual player long before it names a final twelve — eight of the
sixteen still list a pool — and the tracker cannot express that. `final_twelve`
in the generated file means only "this list is 12 names long".

It carries no club affiliation either, so it can never say who is in the WNBA.
That mapping is exactly what `rosters.yaml` exists for, and stays hand-edited.

What it *is* authoritative for is spelling, sometimes. `fiba-wwc check` matches
every player against it and fails on any difference that has not been reviewed.

Four of our names had the wrong *letters* and were corrected against it:
`Sowha`→`Sowah`, `Joklava`→`Joklová`, `Florenz`→`Flórez`, `Valariane`→`Valériane`.
But fifteen names now differ from FIBA's spelling deliberately, each recorded as
`fiba_name:`. Most are diacritics FIBA strips — and it strips them unevenly,
keeping the ü in "Bühner" while dropping the ö from "Geiselsoder" in the same
list, so its stripped forms are not evidence a name is unaccented. The rest:
it abbreviates given names
(Steph/Stephanie), writes Chinese names given-name-first where we and the WNBA
use surname-first (Han Xu, Li Yueru), uses a typographic apostrophe in A'ja
Wilson, and still lists Megan DiLeo under her former surname.

So the rule is: take FIBA's letters, keep our diacritics.

### Where the hand-edited data came from

`data/schedule.yaml` was transcribed from FIBA's official schedule PDF;
`data/rosters.yaml` from a High Post Hoops article of 7 Aug 2026. Both are
third-party documents and neither is committed — they are provenance, not build
inputs, and nothing in the build reads them. `uv run fiba-wwc fetch-sources`
re-downloads both into `sources/` (gitignored) when a transcription needs
re-checking.

## Updating during the tournament

**A knockout matchup is decided.** Nothing to edit — `uv run fiba-wwc scrape &&
uv run fiba-wwc generate`. A bracket slot sits in FIBA's listing from day one
with empty team codes and a 22:00 UTC placeholder; both flip together when the
matchup is decided, so non-empty team codes are the signal that the row is real.
The scrape picks up the teams and the actual tip-off, and `schedule.yaml` keeps
only the PDF-derived skeleton (date, candidate slots, "2nd A - 3rd B").

A value hand-set in `schedule.yaml` still wins, so it remains available as an
override if FIBA is wrong.

**A national roster is finalised.** Run `uv run fiba-wwc scrape-rosters` and read
the diff — a nation dropping to 12 names is a squad that has been cut. Then flip
that player's `status` to `confirmed` in `data/rosters.yaml`, or add a line.
`--confirmed-only` hides everything still speculative. The status stays a human
judgement; see above for why the tracker cannot make it.

**Broadcast listings appear.** Same `uv run fiba-wwc scrape`. FIBA only publishes
a game page once the matchup exists, so the 12 knockout games report as "still
TBD" until then — that is expected, not an error.

## Broadcast listings are per-country

Rights differ by territory: a single game lists 14–29 broadcasters, and across
the tournament they cover 212 territories. The scrape stores every carrier with
the territories it holds rights in, so one scrape serves every country and the
filtering happens at render time.

```sh
uv run fiba-wwc generate --viewer-country FR    # build the page for France
```

**The published page does not need rebuilding for this.** `docs/index.html`
carries the whole broadcaster table (~60KB of JSON, a few KB after compression)
and offers two dropdowns — time zone and viewing country — so a reader in New
York can switch to Eastern and a reader in Canada can see Canadian carriers,
without a rebuild. The page is server-rendered as Pacific/US and the script only
mutates it when a dropdown changes, so it still works with JavaScript off, still
prints correctly, and the choice is remembered in `localStorage`.

For Hungary–France that difference is real: US viewers get Courtside 1891 and
TNT; French viewers get TFX among others. The `.ics` feed is still built for one
country — times in it are UTC-anchored so they are correct everywhere, but the
broadcaster line in each event description is not.

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
