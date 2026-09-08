"""Load the YAML data files, validate them, and join into render-ready objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yaml

from .paths import ROSTERS_YAML, SCHEDULE_YAML, WNBA_TEAMS_YAML
from .scrape import broadcasters_for, load_scraped

GAME_LENGTH = timedelta(hours=2)

#: FIBA's wording for a bracket slot that feeds off another game, as it appears
#: in teamAFrom/teamBFrom: "Winner of Game 26", "Loser of Game 33". The other
#: form, "1st of group D", names no game and so resolves to nothing.
FEEDER = re.compile(r"^(?:winner|loser) of game (\d+)$", re.I)


@dataclass(frozen=True)
class WnbaTeam:
    abbr: str
    name: str
    city: str
    logo_id: int
    primary: str
    secondary: str


@dataclass(frozen=True)
class Player:
    name: str
    wnba: WnbaTeam
    status: str

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass(frozen=True)
class Nation:
    code: str
    name: str
    flag: str
    group: str | None
    players: tuple[Player, ...]


@dataclass
class Game:
    number: int
    phase: str
    group: str | None
    label: str | None
    home: Nation | None
    away: Nation | None
    tip_utc: datetime | None  # None when the slot is not yet assigned
    tip_options_utc: tuple[datetime, ...]
    venue: str | None
    url: str | None
    broadcasters: tuple[dict, ...]
    #: FIBA's wording for where each side comes from, e.g. "Winner of Game 26".
    home_from: str | None = None
    away_from: str | None = None
    #: The nations a pending side can still turn out to be, filled in by load()
    #: when the game it feeds off is itself decided. Empty when it is not.
    home_candidates: tuple[Nation, ...] = field(default_factory=tuple)
    away_candidates: tuple[Nation, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        """Both teams known -- i.e. this is a real matchup, not a bracket slot."""
        return self.home is not None and self.away is not None

    @property
    def half_resolved(self) -> bool:
        """Exactly one side decided -- "USA vs Winner of Game 26"."""
        return (self.home is None) != (self.away is None)

    @property
    def start_utc(self) -> datetime:
        """Best available start time: the assigned slot, else the earliest option."""
        return self.tip_utc or self.tip_options_utc[0]

    @property
    def end_utc(self) -> datetime:
        """When the game can no longer be in progress.

        For a game whose slot is still unassigned this spans the whole candidate
        window -- earliest possible tip to latest possible final buzzer -- rather
        than guessing one slot and blocking two hours around it.

        Guessing cannot be made safe here: the candidate slots are 3 to 3.5 hours
        apart and a game runs 2, so whichever single slot you pick, the block
        misses the game entirely if the other one is the real one. A wide
        placeholder is honest about the uncertainty and is replaced by the exact
        time as soon as FIBA publishes the matchup.
        """
        if self.tip_utc is not None:
            return self.tip_utc + GAME_LENGTH
        return self.tip_options_utc[-1] + GAME_LENGTH

    @property
    def tentative(self) -> bool:
        return self.tip_utc is None or not self.resolved

    def start_in(self, tz: ZoneInfo) -> datetime:
        return self.start_utc.astimezone(tz)

    def _sides(self) -> tuple[tuple, tuple]:
        return (
            (self.home, self.home_candidates, self.home_from),
            (self.away, self.away_candidates, self.away_from),
        )

    @staticmethod
    def _side_name(nation, candidates, origin) -> str:
        """One half of a matchup, at the best precision available.

        A decided nation beats the two it could have been, which in turn beats
        FIBA's bare "Winner of Game 29" -- the last of which is all there is for
        a slot fed by a game that has not been played either.
        """
        if nation is not None:
            return nation.name
        if candidates:
            return "/".join(n.name for n in candidates)
        return origin or "TBD"

    def title(self) -> str:
        if self.resolved:
            return f"{self.home.name} vs {self.away.name}"
        if any(x for side in self._sides() for x in side):
            return " vs ".join(self._side_name(*side) for side in self._sides())
        return self.label or f"Game {self.number}"

    @property
    def matchup_note(self) -> str | None:
        """Which game decides a side that the title is showing as candidates.

        Only for sides where the candidates replaced FIBA's wording: if the
        title already reads "Winner of Game 29", repeating it here says nothing.
        """
        refs = [o for n, c, o in self._sides() if n is None and c and o]
        return " · ".join(r[:1].lower() + r[1:] for r in refs) or None

    def nations(self) -> list[Nation]:
        return [n for n in (self.home, self.away) if n is not None]

    def broadcasters_in(self, country: str) -> list[dict]:
        """Carriers holding rights in one country, as `{name, url}`."""
        return broadcasters_for(list(self.broadcasters), country)


@dataclass
class Tournament:
    name: str
    city: str
    local_tz: ZoneInfo
    games: list[Game]
    nations: dict[str, Nation]
    wnba_teams: dict[str, WnbaTeam]

    def games_in_order(self) -> list[Game]:
        return sorted(self.games, key=lambda g: (g.start_utc, g.number))


def _resolve_candidates(games: list[Game]) -> None:
    """Narrow each pending side to the nations it can still be.

    "Winner of Game 26" is only a name until you notice game 26 is Hungary
    against Japan, at which point the slot is worth showing as "Hungary/Japan".
    That resolution is deliberately one step deep: a semi-final fed by a
    quarter-final that has not been played has four possible nations, not two,
    and listing four would be less informative than FIBA's own wording. Those
    keep an empty candidate tuple and fall back to it.
    """
    by_number = {g.number: g for g in games}

    def candidates(origin: str | None) -> tuple[Nation, ...]:
        m = FEEDER.match((origin or "").strip())
        if not m:
            return ()
        feeder = by_number.get(int(m.group(1)))
        if feeder is None or not feeder.resolved:
            return ()
        return tuple(n for n in (feeder.home, feeder.away) if n is not None)

    for g in games:
        if g.home is None:
            g.home_candidates = candidates(g.home_from)
        if g.away is None:
            g.away_candidates = candidates(g.away_from)


def _parse_utc(day: date, hhmm: str) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=UTC)


def load(include_unconfirmed: bool = True) -> Tournament:
    schedule = yaml.safe_load(SCHEDULE_YAML.read_text(encoding="utf-8"))
    rosters = yaml.safe_load(ROSTERS_YAML.read_text(encoding="utf-8")) or {}
    teams_raw = yaml.safe_load(WNBA_TEAMS_YAML.read_text(encoding="utf-8"))
    scraped = load_scraped()

    wnba = {abbr: WnbaTeam(abbr=abbr, **spec) for abbr, spec in teams_raw.items()}

    group_of = {code: letter for letter, codes in schedule["groups"].items() for code in codes}

    # --- validate the hand-edited files against each other ------------------ #
    for nation_code, players in rosters.items():
        if nation_code not in schedule["teams"]:
            raise ValueError(f"rosters.yaml has nation {nation_code!r}, which is not competing")
        for p in players:
            if p["wnba"] not in wnba:
                raise ValueError(f"{p['name']}: unknown WNBA team {p['wnba']!r}")
            if p["status"] not in {"confirmed", "unconfirmed"}:
                raise ValueError(f"{p['name']}: bad status {p['status']!r}")

    nations: dict[str, Nation] = {}
    for code, spec in schedule["teams"].items():
        players = tuple(
            Player(name=p["name"], wnba=wnba[p["wnba"]], status=p["status"])
            for p in rosters.get(code, [])
            if include_unconfirmed or p["status"] == "confirmed"
        )
        nations[code] = Nation(
            code=code,
            name=spec["name"],
            flag=spec.get("flag", ""),
            group=group_of.get(code),
            players=tuple(sorted(players, key=lambda p: (not p.confirmed, p.wnba.abbr, p.name))),
        )

    seen_numbers: set[int] = set()
    games: list[Game] = []
    for raw in schedule["games"]:
        number = raw["number"]
        if number in seen_numbers:
            raise ValueError(f"duplicate game number {number}")
        seen_numbers.add(number)

        day = raw["date_utc"]
        tip = _parse_utc(day, raw["tip_utc"]) if raw.get("tip_utc") else None
        options = tuple(_parse_utc(day, t) for t in raw.get("tip_utc_options", []))
        if tip is None and not options:
            raise ValueError(f"game {number} has neither tip_utc nor tip_utc_options")

        extra = scraped.get(number) or {}

        # A knockout matchup is a bracket slot until FIBA decides it. schedule.yaml
        # holds the PDF-derived skeleton -- date, candidate slots, "2nd A - 3rd B"
        # -- and the scrape fills in the teams and the real tip-off once they
        # exist, so resolving a matchup needs no hand-edit. A hand-set value in
        # schedule.yaml still wins, so it stays available as an override.
        home_code = raw.get("home") or extra.get("home")
        away_code = raw.get("away") or extra.get("away")
        for code in (home_code, away_code):
            if code and code not in nations:
                raise ValueError(f"game {number}: unknown nation code {code!r}")
        home = nations[home_code] if home_code else None
        away = nations[away_code] if away_code else None

        if tip is None and extra.get("tip_utc"):
            tip = datetime.fromisoformat(extra["tip_utc"]).replace(tzinfo=UTC)
        if raw.get("group") and home and away:
            for n in (home, away):
                if n.group != raw["group"]:
                    raise ValueError(
                        f"game {number}: {n.code} is in group {n.group}, not {raw['group']}"
                    )

        games.append(
            Game(
                number=number,
                phase=raw["phase"],
                group=raw.get("group"),
                label=raw.get("label"),
                home=home,
                away=away,
                tip_utc=tip,
                tip_options_utc=options,
                venue=extra.get("venue"),
                url=extra.get("url"),
                broadcasters=tuple(extra.get("broadcasters") or []),
                home_from=extra.get("home_from"),
                away_from=extra.get("away_from"),
            )
        )

    _resolve_candidates(games)

    return Tournament(
        name=schedule["tournament"]["name"],
        city=schedule["tournament"]["city"],
        local_tz=ZoneInfo(schedule["tournament"]["local_tz"]),
        games=games,
        nations=nations,
        wnba_teams=wnba,
    )
