"""Load the YAML data files, validate them, and join into render-ready objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yaml

from .paths import ROSTERS_YAML, SCHEDULE_YAML, WNBA_TEAMS_YAML
from .scrape import broadcasters_for, load_scraped

GAME_LENGTH = timedelta(hours=2)


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

    @property
    def resolved(self) -> bool:
        """Both teams known -- i.e. this is a real matchup, not a bracket slot."""
        return self.home is not None and self.away is not None

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

    def title(self) -> str:
        if self.resolved:
            return f"{self.home.name} vs {self.away.name}"
        return self.label or f"Game {self.number}"

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
            )
        )

    return Tournament(
        name=schedule["tournament"]["name"],
        city=schedule["tournament"]["city"],
        local_tz=ZoneInfo(schedule["tournament"]["local_tz"]),
        games=games,
        nations=nations,
        wnba_teams=wnba,
    )
