from dataclasses import dataclass
from datetime import date
from typing import Literal

from engine.candidates import generate_candidates, violates
from engine.explain import join_pt
from engine.models import (
    Budget,
    DateRange,
    Destination,
    ExcludeClimate,
    ExcludeDestination,
    HardConstraint,
    Member,
    PreferDestination,
    PreferPace,
    TripInput,
)
from engine.summaries import format_date_range

# Mapa de tensões: compatibilidade entre pares, principais restrições e
# viabilidade por destino, só com quem já respondeu (trip.members).
#
# Orçamento é confidencial: ele nunca vira aresta entre duas pessoas, porque a
# aresta identificaria quem tem o limite, e não conta para destacar quem tem
# "mais limites". O que um orçamento elimina aparece em key_constraints, sem
# nome ("O orçamento de um participante elimina Paraty.").

TensionCriterion = Literal["dates", "climate", "pace"]

#: Menos dias em comum que isso entre dois limites de data é conflito.
MIN_COMMON_DAYS = 4
#: Só preferências de ritmo fortes (peso a partir disso) geram conflito.
STRONG_PREFERENCE_WEIGHT = 0.8
#: Mínimo de limites, sem contar orçamento, para alguém ser destacado como quem tem "mais limites".
MIN_LIMITS_FOR_MOST_RESTRICTIVE = 2
#: Ordem de prioridade quando um par conflita em mais de um critério.
CRITERION_PRIORITY: tuple[TensionCriterion, ...] = ("dates", "climate", "pace")

LIMIT_LABEL = {ExcludeClimate: "O limite de clima", ExcludeDestination: "O veto"}


@dataclass(frozen=True)
class MemberPair:
    member_a_id: str
    member_b_id: str
    status: Literal["compatible", "conflict"]
    #: Critério principal do conflito; nulo quando o par é compatível.
    criterion: TensionCriterion | None


@dataclass(frozen=True)
class KeyConstraint:
    id: str
    summary: str


@dataclass(frozen=True)
class DestinationViability:
    destination_id: str
    #: Quantos dos que responderam aceitam o destino (nenhum limite o elimina).
    accepted_count: int
    responded_count: int


@dataclass(frozen=True)
class Tensions:
    most_restrictive_member_id: str | None
    pairs: tuple[MemberPair, ...]
    key_constraints: tuple[KeyConstraint, ...]
    viability: tuple[DestinationViability, ...]


def tensions(trip: TripInput, names: dict[str, str]) -> Tensions:
    """
    trip.members são só os que responderam, na ordem em que devem aparecer.
    names traz o nome de cada um, para os resumos de limites que não são de
    orçamento.
    """
    eliminated = _eliminated_by_limit(trip)
    members = trip.members
    destinations = sorted(trip.destinations, key=lambda item: item.id)
    return Tensions(
        most_restrictive_member_id=_most_restrictive(members),
        pairs=_pairs(members, destinations, eliminated),
        key_constraints=_key_constraints(trip, names, destinations, eliminated),
        viability=tuple(
            DestinationViability(
                destination.id,
                sum(
                    1
                    for member in members
                    if not any(destination.id in eliminated[(member.id, c.id)] for c in member.hard)
                ),
                len(members),
            )
            for destination in destinations
        ),
    )


def _eliminated_by_limit(trip: TripInput) -> dict[tuple[str, str], set[str]]:
    """
    Destinos que cada limite elimina sozinho: nenhum roteiro do destino o
    respeita, como no motor. O orçamento é comparado com o roteiro mais barato,
    e um limite de datas que não comporta nem o roteiro curto elimina todos.
    """
    candidates = list(generate_candidates(trip))
    result: dict[tuple[str, str], set[str]] = {}
    for member in trip.members:
        for constraint in member.hard:
            result[(member.id, constraint.id)] = {
                destination.id
                for destination in trip.destinations
                if all(violates(c, constraint) for c in candidates if c.destination.id == destination.id)
            }
    return result


def _preferred(member: Member) -> set[str]:
    return {i for item in member.soft if isinstance(item, PreferDestination) for i in item.destination_ids}


def _date_ranges(member: Member) -> list[DateRange]:
    return [item for item in member.hard if isinstance(item, DateRange)]


def _conflicts(
    a: Member, b: Member, destinations: list[Destination], eliminated: dict[tuple[str, str], set[str]]
) -> list[TensionCriterion]:
    found: set[TensionCriterion] = set()

    for range_a in _date_ranges(a):
        for range_b in _date_ranges(b):
            common_days = (min(range_a.end, range_b.end) - max(range_a.start, range_b.start)).days + 1
            if common_days < MIN_COMMON_DAYS:
                found.add("dates")

    # O limite de clima de um elimina um destino que o outro prefere. Orçamento
    # não entra: a aresta diria de quem é o limite.
    for limited, other in ((a, b), (b, a)):
        preferred = _preferred(other) & {d.id for d in destinations}
        for constraint in limited.hard:
            if isinstance(constraint, ExcludeClimate) and preferred & eliminated[(limited.id, constraint.id)]:
                found.add("climate")

    def strong_paces(member: Member) -> set[str]:
        return {
            item.pace
            for item in member.soft
            if isinstance(item, PreferPace) and item.weight >= STRONG_PREFERENCE_WEIGHT
        }

    paces = strong_paces(a), strong_paces(b)
    if ("relaxed" in paces[0] and "intense" in paces[1]) or ("intense" in paces[0] and "relaxed" in paces[1]):
        found.add("pace")

    return [criterion for criterion in CRITERION_PRIORITY if criterion in found]


def _pairs(
    members: tuple[Member, ...], destinations: list[Destination], eliminated: dict[tuple[str, str], set[str]]
) -> tuple[MemberPair, ...]:
    pairs: list[MemberPair] = []
    for index, a in enumerate(members):
        for b in members[index + 1 :]:
            criteria = _conflicts(a, b, destinations, eliminated)
            criterion = criteria[0] if criteria else None
            pairs.append(MemberPair(a.id, b.id, "conflict" if criterion else "compatible", criterion))
    return tuple(pairs)


def _counted_limits(member: Member) -> int:
    return sum(1 for item in member.hard if not isinstance(item, Budget))


def _most_restrictive(members: tuple[Member, ...]) -> str | None:
    """Quem tem pelo menos 2 limites, sem contar orçamento, e estritamente mais que todos os outros."""
    counts = [_counted_limits(member) for member in members]
    top = max(counts, default=0)
    if top < MIN_LIMITS_FOR_MOST_RESTRICTIVE or counts.count(top) > 1:
        return None
    return members[counts.index(top)].id


def _key_constraints(
    trip: TripInput,
    names: dict[str, str],
    destinations: list[Destination],
    eliminated: dict[tuple[str, str], set[str]],
) -> tuple[KeyConstraint, ...]:
    items: list[KeyConstraint] = []
    members = trip.members

    def eliminated_destinations(member: Member, constraint: HardConstraint) -> list[Destination]:
        return [d for d in destinations if d.id in eliminated[(member.id, constraint.id)]]

    # Orçamento sem nome e sem dizer quem prefere o destino eliminado. Orçamentos
    # que eliminam os mesmos destinos viram um item só.
    for member in members:
        for constraint in member.hard:
            if not isinstance(constraint, Budget):
                continue
            gone = eliminated_destinations(member, constraint)
            if not gone:
                continue
            key = f"budget:{','.join(d.id for d in gone)}"
            if any(item.id == key for item in items):
                continue
            summary = f"O orçamento de um participante elimina {join_pt([d.name for d in gone])}."
            items.append(KeyConstraint(key, summary))

    for member in members:
        for constraint in member.hard:
            label = LIMIT_LABEL.get(type(constraint))
            gone = eliminated_destinations(member, constraint)
            if label is None or not gone:
                continue
            summary = f"{label} de {names[member.id]} elimina {join_pt([d.name for d in gone])}"
            if len(gone) == 1:
                fans = [other for other in members if other is not member and gone[0].id in _preferred(other)]
                if fans:
                    verb = "prefere" if len(fans) == 1 else "preferem"
                    summary += f", que {join_pt([names[fan.id] for fan in fans])} {verb}"
            items.append(KeyConstraint(f"{member.id}:{constraint.id}", f"{summary}."))

    # Janela comum: interseção da janela da viagem com todos os limites de data.
    ranges = [item for member in members for item in _date_ranges(member)]
    if ranges:
        start: date = max([trip.window_start, *(item.start for item in ranges)])
        end: date = min([trip.window_end, *(item.end for item in ranges)])
        summary = (
            "Não há datas em comum entre todas as respostas."
            if start > end
            else f"A janela comum de datas é de {format_date_range(start, end)}."
        )
        items.append(KeyConstraint("common-dates", summary))

    return tuple(items)
