from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from engine.models import (
    Budget,
    DateRange,
    Destination,
    ExcludeClimate,
    ExcludeDestination,
    ExcludeTags,
    HardConstraint,
    LimitKind,
    Member,
    TripInput,
)

SHORT_VARIANT_LABEL = "roteiro curto"
#: Quantas noites a menos tem o roteiro curto.
SHORT_VARIANT_NIGHTS_LESS = 2
MIN_NIGHTS = 2


@dataclass(frozen=True)
class Candidate:
    destination: Destination
    nights: int
    variant_label: str | None
    start: date

    @property
    def end(self) -> date:
        """Dia da volta: com 6 noites, de 12 a 18."""
        return self.start + timedelta(days=self.nights)

    @property
    def cost(self) -> float:
        return self.destination.cost_for(self.nights)


def variants(nights: int) -> list[tuple[int, str | None]]:
    """Roteiro padrão e, se couber, o roteiro curto."""
    result: list[tuple[int, str | None]] = [(nights, None)]
    short = nights - SHORT_VARIANT_NIGHTS_LESS
    if short >= MIN_NIGHTS:
        result.append((short, SHORT_VARIANT_LABEL))
    return result


def generate_candidates(trip: TripInput) -> Iterator[Candidate]:
    """Destino × variante × dia de ida, todos dentro da janela, em ordem estável."""
    for destination in sorted(trip.destinations, key=lambda item: item.id):
        for nights, label in variants(trip.nights):
            start = trip.window_start
            while start + timedelta(days=nights) <= trip.window_end:
                yield Candidate(destination, nights, label, start)
                start += timedelta(days=1)


def violates(candidate: Candidate, constraint: HardConstraint) -> bool:
    match constraint:
        case DateRange(start=start, end=end):
            return candidate.start < start or candidate.end > end
        case Budget(max_per_person=limit):
            return candidate.cost > limit
        case ExcludeClimate(climates=climates):
            return candidate.destination.climate in climates
        case ExcludeDestination(destination_ids=ids):
            return candidate.destination.id in ids
        case ExcludeTags(tags=tags):
            return bool(tags & set(candidate.destination.tags))


def limit_kind(constraint: HardConstraint) -> LimitKind:
    match constraint:
        case DateRange():
            return "date_range"
        case Budget():
            return "budget"
        case ExcludeClimate():
            return "exclude_climate"
        case ExcludeDestination():
            return "exclude_destination"
        case ExcludeTags():
            return "exclude_tags"


def violations(candidate: Candidate, members: tuple[Member, ...]) -> list[tuple[str, str]]:
    """Pares (member_id, constraint_id) de cada limite que o candidato fere."""
    return [
        (member.id, constraint.id)
        for member in members
        for constraint in member.hard
        if violates(candidate, constraint)
    ]
