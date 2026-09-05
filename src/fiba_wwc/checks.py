"""Self-checks over the data files. Run with `fiba-wwc check`.

These guard the things that are easy to get silently wrong: a mistyped tip-off,
a roster pointing at a club that does not exist, a tracking param sneaking back
into a stored URL, a scrape that matched two schedule games to one FIBA game.
"""

from __future__ import annotations

from collections import Counter
from zoneinfo import ZoneInfo

import yaml

from .data import load
from .paths import CACHE, ROSTERS_YAML, SCHEDULE_YAML, SCRAPED_YAML
from .scrape import extract_games
from .tracker import find_player, load_squads
from .urls import clean_url


class CheckFailure(Exception):
    pass


def _require(cond, msg):
    if not cond:
        raise CheckFailure(msg)


def check_structure(report):
    t = load()
    _require(len(t.games) == 36, f"expected 36 games, got {len(t.games)}")
    group = [g for g in t.games if g.phase == "group"]
    _require(len(group) == 24, f"expected 24 group games, got {len(group)}")

    played = Counter()
    for g in group:
        played[g.home.code] += 1
        played[g.away.code] += 1
    _require(len(played) == 16, f"expected 16 nations, got {len(played)}")
    _require(
        set(played.values()) == {3},
        f"every nation must play 3 group games, got {sorted(set(played.values()))}",
    )
    report("structure", "36 games, 24 group, 16 nations x 3 group games each")


def check_urls(report):
    """No tracking params may survive into stored data."""
    probe = (
        "https://www.dazn.com/en-CH/competition/Competition:66byt"
        "?utm_source=fibaweb&utm_medium=referral&utm_campaign=x&utm_content=y"
    )
    _require(
        clean_url(probe) == "https://www.dazn.com/en-CH/competition/Competition:66byt",
        "clean_url did not strip the FIBA broadcaster utm params",
    )

    scraped = yaml.safe_load(SCRAPED_YAML.read_text(encoding="utf-8")) or {}
    dirty = [
        b["url"]
        for e in scraped.values()
        for b in (e.get("broadcasters") or [])
        if b.get("url") and ("utm_" in b["url"] or "referral" in b["url"])
    ]
    _require(not dirty, f"tracking params in stored URLs: {dirty}")
    report("urls", "clean_url strips utm_/referral; no stored URL carries them")


def check_scrape_mapping(report):
    scraped = yaml.safe_load(SCRAPED_YAML.read_text(encoding="utf-8")) or {}
    if not scraped:
        report("scrape", "SKIPPED - no data/fiba_scraped.yaml yet, run `fiba-wwc scrape`")
        return
    _require(
        sorted(scraped) == list(range(1, 37)),
        f"scraped file should cover games 1..36, has {sorted(scraped)}",
    )
    ids = [e["fiba_game_id"] for e in scraped.values()]
    _require(len(set(ids)) == len(ids), "two schedule games mapped to one FIBA gameId")
    _require(scraped[1]["url"].endswith("128116-JPN-MLI"), scraped[1]["url"])
    _require(scraped[4]["url"].endswith("128122-HUN-FRA"), scraped[4]["url"])
    report("scrape", f"{len(scraped)} games mapped 1:1 to distinct FIBA gameIds")


def check_times_against_fiba(report):
    """Cross-check the hand-transcribed PDF times against FIBA's gameDateTimeUTC.

    Only possible when a cached listing page is around; skipped otherwise.
    """
    pages = [p for p in CACHE.glob("*games.html")] if CACHE.exists() else []
    if not pages:
        report("times", "SKIPPED - no cached listing page, run `fiba-wwc scrape`")
        return
    games = extract_games(max(pages, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"))
    _require(games, "could not parse the cached listing page")

    schedule = yaml.safe_load(SCHEDULE_YAML.read_text(encoding="utf-8"))
    sched = {g["number"]: g for g in schedule["games"]}
    mismatches, checked = [], 0
    for fg in games:
        a = (fg.get("teamA") or {}).get("code")
        b = (fg.get("teamB") or {}).get("code")
        if not (a and b):
            continue  # unresolved slots carry a placeholder datetime
        hit = [n for n, s in sched.items() if s.get("home") == a and s.get("away") == b]
        _require(len(hit) == 1, f"{a}-{b} matched {len(hit)} schedule games")
        s = sched[hit[0]]
        mine = f"{s['date_utc']}T{s['tip_utc']}:00"
        if mine != fg["gameDateTimeUTC"]:
            mismatches.append(f"game {hit[0]} {a}-{b}: ours {mine} vs FIBA {fg['gameDateTimeUTC']}")
        checked += 1
    _require(not mismatches, "schedule disagrees with FIBA:\n  " + "\n  ".join(mismatches))
    report("times", f"{checked} tip-offs match FIBA's own gameDateTimeUTC exactly")


def check_timezone(report):
    t = load()
    pt = ZoneInfo("America/Los_Angeles")
    by_num = {g.number: g for g in t.games}
    cases = [
        (1, "Fri 2026-09-04 02:30"),  # 09:30 UTC, earliest slot
        (20, "Mon 2026-09-07 11:45"),  # 18:45 UTC
        (36, "Sun 2026-09-13 11:00"),  # the final, 18:00 UTC
    ]
    for num, want in cases:
        got = by_num[num].start_in(pt).strftime("%a %Y-%m-%d %H:%M")
        _require(got == want, f"game {num}: expected {want} PT, got {got}")
    report("timezone", "game 1 = 2:30am PT Fri; game 20 = 11:45am PT; final = 11:00am PT Sun")


def check_rosters(report):
    t = load()
    total = sum(len(n.players) for n in t.nations.values())
    gsv = sorted(
        (p.name, n.code) for n in t.nations.values() for p in n.players if p.wnba.abbr == "GSV"
    )
    want = sorted(
        [
            ("Cecilia Zandalasini", "ITA"),
            ("Gabby Williams", "FRA"),
            ("Janelle Salaün", "FRA"),
            ("Miela Sowah", "AUS"),
        ]
    )
    _require(gsv == want, f"Golden State roster drifted from the source article: {gsv}")
    report(
        "rosters",
        f"{total} players; Golden State's 4 across AUS/FRA/ITA match the source article",
    )


def check_roster_names_against_fiba(report):
    """Our player spellings, against FIBA's official roster tracker.

    Reports rather than enforces, in both directions:

    * a player FIBA's squad does not contain at all is a hard failure -- either
      the name is wrong or they have been left out of a published squad
    * a player matched only *inexactly* also fails, because every difference
      that exists today has been reviewed and recorded. Some were our typo,
      some are FIBA's (it strips diacritics unevenly and has its own slips),
      and some are deliberate -- we keep the fuller given name, Chinese
      surname-first order, and a player's current surname where FIBA still
      lists the old one. Setting ``fiba_name`` on the player in rosters.yaml
      records "reviewed, keeping ours" and settles it. So an unreviewed
      difference means something moved since, and wants a human: either our
      spelling is wrong or it is a divergence worth recording.

    The matcher is deliberately tolerant -- it has to be, to survive FIBA's
    uneven diacritics -- which is exactly why a merely-close match cannot pass
    silently. "Kelsey Plumm" matches "Kelsey Plum" on the prefix rule; only
    failing on the inexactness catches that typo.

    This never touches ``status``. A federation can confirm an individual long
    before it cuts to twelve, which is precisely what the tracker cannot say.
    """
    squads = load_squads()
    if not squads:
        report("names", "SKIPPED - no data/fiba_rosters.yaml, run `fiba-wwc scrape-rosters`")
        return

    rosters = yaml.safe_load(ROSTERS_YAML.read_text(encoding="utf-8")) or {}
    missing, inexact, total = [], [], 0
    for code, players in sorted(rosters.items()):
        squad = squads.get(code, {}).get("players")
        if not squad:
            continue
        for player in players:
            total += 1
            alias = player.get("fiba_name")
            hit = find_player(player["name"], squad, alias=alias)
            if hit is None:
                missing.append(f"{code} {player['name']!r}")
            elif hit != player["name"] and not alias:
                # An alias is a recorded decision, so it is not news.
                inexact.append(f"{code} {player['name']!r} vs FIBA {hit!r}")

    _require(
        not missing,
        "not found in FIBA's published squad (wrong spelling, or left out): " + "; ".join(missing),
    )
    _require(
        not inexact,
        "spelling differs from FIBA and has not been reviewed -- correct ours, or "
        "record the divergence with fiba_name: " + "; ".join(inexact),
    )

    named = sum(1 for e in squads.values() if e["final_twelve"])
    aliased = sum(1 for ps in rosters.values() for p in ps if p.get("fiba_name"))
    report(
        "names",
        f"{total} players match FIBA's squads across {len(squads)} nations "
        f"({named} cut to a final twelve, {aliased} spellings deliberately ours)",
    )


def check_rosters_against_final_twelves(report):
    """Our WNBA players against the twelve each federation actually published.

    The name check below asks only whether FIBA's squad *contains* a player. It
    cannot see the two failures that matter once squads lock:

    * someone in rosters.yaml who did not make the twelve -- they are being
      rendered onto a schedule for games they will not play
    * a squad member at a WNBA club who is missing from rosters.yaml -- a WNBA
      player the site silently omits

    Both are live risks for the whole tournament, not just at cut time: an
    injury replacement rewrites a twelve mid-event, and this is what notices.

    ``wnba`` is a floor. FIBA lists a developmental player at her European club
    -- Elizabeth Balogun reads as Valencia, not New York -- so a missing one of
    those is invisible here and only WNBA.com's list will show it. That makes
    an omission possible; it does not make one silent, because the player would
    still have to be absent from rosters.yaml to matter.
    """
    squads = load_squads()
    if not squads:
        report("twelves", "SKIPPED - no data/fiba_rosters.yaml, run `fiba-wwc scrape-rosters`")
        return

    rosters = yaml.safe_load(ROSTERS_YAML.read_text(encoding="utf-8")) or {}
    dropped, absent, locked = [], [], 0
    for code, squad in sorted(squads.items()):
        # A nation still on a preselect pool has not decided anything yet.
        if not squad.get("final_twelve"):
            continue
        locked += 1
        names = squad["players"]
        ours = rosters.get(code) or []
        for player in ours:
            if find_player(player["name"], names, alias=player.get("fiba_name")) is None:
                dropped.append(f"{code} {player['name']!r}")
        for name, club in sorted((squad.get("wnba") or {}).items()):
            if not any(
                find_player(p["name"], [name], alias=p.get("fiba_name")) for p in ours
            ):
                absent.append(f"{code} {name!r} ({club})")

    _require(
        not dropped,
        "in rosters.yaml but not on the twelve their federation published -- cut, "
        "replaced, or injured: " + "; ".join(dropped),
    )
    _require(
        not absent,
        "on a published twelve at a WNBA club but missing from rosters.yaml: "
        + "; ".join(absent),
    )
    total = sum(len(rosters.get(c) or []) for c in squads if squads[c].get("final_twelve"))
    report(
        "twelves",
        f"{total} players all on the twelves FIBA published, across {locked} locked squads",
    )


CHECKS = [
    check_structure,
    check_rosters,
    check_timezone,
    check_urls,
    check_scrape_mapping,
    check_times_against_fiba,
    check_roster_names_against_fiba,
    check_rosters_against_final_twelves,
]


def run_all() -> int:
    failures = 0

    def report(name, msg):
        print(f"  \033[32mok\033[0m  {name:10} {msg}")

    for check in CHECKS:
        try:
            check(report)
        except CheckFailure as exc:
            failures += 1
            print(f"  \033[31mFAIL\033[0m {check.__name__}: {exc}")
    print()
    print("all checks passed" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0
