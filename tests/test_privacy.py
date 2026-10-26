from dataclasses import asdict, replace
from datetime import date

import pytest

from engine import run
from engine.models import Budget, DateRange, EngineInputError, ExcludeTags, Member, MemberLimit
from engine.privacy import limits_for_member
from tests.fixtures import ANA, BRUNO, CARLA, EVA, JULY_TRIP, trip_with

# Orçamento é confidencial: nas saídas para o grupo, um limite de orçamento
# nunca aparece junto com quem o declarou.

TIGHT_EVA = replace(EVA, hard=(*EVA.hard[:1], Budget("eva-h2", 1000, all_inclusive=True), *EVA.hard[2:]))
BROKE = Member("mem-diego", hard=(Budget("diego-h1", 500, all_inclusive=True),))

NO_BEACH_EVA = replace(EVA, hard=(*EVA.hard, ExcludeTags("eva-h4", frozenset({"praia"}))))

THREE_NIGHTS = Member("mem-diego", hard=(DateRange("diego-h1", date(2027, 7, 12), date(2027, 7, 15)),))

GROUP_SCENARIOS = {
    "viagem de julho": JULY_TRIP,
    "orçamento elimina Paraty": trip_with(members=(ANA, BRUNO, CARLA, TIGHT_EVA)),
    "orçamento inviabiliza tudo": trip_with(members=(ANA, BRUNO, EVA, BROKE)),
    "datas inviabilizam tudo, com orçamento no grupo": trip_with(members=(ANA, BRUNO, EVA, THREE_NIGHTS)),
    "limite de tag com orçamento no grupo": trip_with(members=(ANA, BRUNO, CARLA, NO_BEACH_EVA)),
}


def budget_refs_with_member(value) -> list:
    """Todo dicionário, em qualquer nível, com kind "budget" e member_id preenchido."""
    found = []
    if isinstance(value, dict):
        if value.get("kind") == "budget" and value.get("member_id") is not None:
            found.append(value)
        for item in value.values():
            found += budget_refs_with_member(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found += budget_refs_with_member(item)
    return found


@pytest.mark.parametrize("trip_input", GROUP_SCENARIOS.values(), ids=GROUP_SCENARIOS.keys())
def test_group_output_never_ties_budget_to_a_member(trip_input):
    output = asdict(run(trip_input))
    assert budget_refs_with_member(output) == []


@pytest.mark.parametrize("trip_input", GROUP_SCENARIOS.values(), ids=GROUP_SCENARIOS.keys())
def test_explanations_never_mention_budget(trip_input):
    for plan in run(trip_input).plans:
        for item in plan.explanation:
            assert "orçamento" not in item.text.lower()


def test_limits_for_member_shows_only_that_member():
    assert limits_for_member(JULY_TRIP, "mem-eva") == (
        MemberLimit("eva-h1", "date_range", ()),
        MemberLimit("eva-h2", "budget", ()),
        MemberLimit("eva-h3", "exclude_climate", ("dest-chapada",)),
    )
    assert limits_for_member(JULY_TRIP, "mem-ana") == ()


def test_limits_for_member_names_destinations_the_budget_eliminates():
    trip_input = trip_with(members=(ANA, BRUNO, CARLA, TIGHT_EVA))
    by_id = {item.constraint_id: item for item in limits_for_member(trip_input, "mem-eva")}
    # Paraty custa 1080 até no roteiro curto; os outros cabem em algum roteiro.
    assert by_id["eva-h2"].eliminated_destination_ids == ("dest-paraty",)


def test_date_limit_that_fits_nothing_eliminates_every_destination():
    three_nights = Member("mem-diego", hard=(DateRange("diego-h1", date(2027, 7, 12), date(2027, 7, 15)),))
    (limit,) = limits_for_member(trip_with(members=(ANA, three_nights)), "mem-diego")
    assert limit.eliminated_destination_ids == (
        "dest-chapada",
        "dest-jericoacoara",
        "dest-lencois",
        "dest-paraty",
    )


def test_limits_for_unknown_member_fails():
    with pytest.raises(EngineInputError):
        limits_for_member(JULY_TRIP, "mem-nobody")
