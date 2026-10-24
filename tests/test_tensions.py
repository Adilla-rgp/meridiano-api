from dataclasses import replace

from engine.models import Budget, ExcludeClimate, ExcludeTags
from engine.tensions import KeyConstraint, MemberPair, tensions
from tests.fixtures import ANA, BRUNO, CARLA, DIEGO, EVA, trip_with

# Mapa de tensões da Viagem de julho, os mesmos casos de planner-vite/src/mocks/tensions.test.ts.

NAMES = {"mem-ana": "Ana", "mem-bruno": "Bruno", "mem-carla": "Carla", "mem-eva": "Eva", "mem-diego": "Diego"}

#: Eva com orçamento de R$ 1.000: Paraty não cabe nem no roteiro curto (R$ 1.080).
TIGHT_EVA = replace(EVA, hard=(EVA.hard[0], Budget("eva-h2", 1000, all_inclusive=True), EVA.hard[2]))


def tensions_with(*members):
    return tensions(trip_with(members=(ANA, BRUNO, CARLA, *members)), NAMES)


def test_never_links_two_members_by_budget():
    for result in (tensions_with(EVA), tensions_with(TIGHT_EVA)):
        assert "budget" not in [pair.criterion for pair in result.pairs]


def test_shows_what_a_budget_eliminates_without_saying_whose():
    items = tensions_with(TIGHT_EVA).key_constraints
    budget = [item for item in items if "orçamento" in item.summary]
    assert budget == [KeyConstraint("budget:dest-paraty", "O orçamento de um participante elimina Paraty.")]
    assert all("eva-h2" not in item.id for item in items)


def test_compares_budget_with_the_cheapest_variant():
    # R$ 1.100 não cobre Paraty com 6 noites (R$ 1.380), mas cobre o roteiro curto (R$ 1.080).
    result = tensions_with(EVA)
    assert not any("orçamento" in item.summary for item in result.key_constraints)
    paraty = next(item for item in result.viability if item.destination_id == "dest-paraty")
    assert paraty.accepted_count == 4


def test_budget_does_not_count_for_most_limits():
    # Eva tem 3 limites, um deles de orçamento. Com um segundo limite, Bruno empata com ela.
    assert tensions_with(EVA).most_restrictive_member_id == "mem-eva"
    bruno = replace(BRUNO, hard=(*BRUNO.hard, ExcludeClimate("bruno-h2", frozenset({"cold"}))))
    result = tensions(trip_with(members=(ANA, bruno, CARLA, EVA)), NAMES)
    assert result.most_restrictive_member_id is None


def test_keeps_the_name_on_limits_other_than_budget():
    result = tensions_with(EVA)
    assert "O limite de clima de Eva elimina Chapada Diamantina, que Carla prefere." in [
        item.summary for item in result.key_constraints
    ]
    assert MemberPair("mem-carla", "mem-eva", "conflict", "climate") in result.pairs


def test_tag_limit_is_named_like_other_limits():
    bruno = replace(BRUNO, hard=(*BRUNO.hard, ExcludeTags("bruno-h2", frozenset({"vida noturna"}))))
    result = tensions(trip_with(members=(ANA, bruno, CARLA, EVA)), NAMES)
    assert "O limite de tipo de destino de Bruno elimina Jericoacoara." in [
        item.summary for item in result.key_constraints
    ]
    jeri = next(item for item in result.viability if item.destination_id == "dest-jericoacoara")
    assert jeri.accepted_count == 3


def test_date_limit_shorter_than_the_short_variant_eliminates_every_destination():
    result = tensions_with(EVA, DIEGO)
    assert all(item.accepted_count < item.responded_count for item in result.viability)
    assert result.key_constraints[-1] == KeyConstraint(
        "common-dates", "A janela comum de datas é de 12 a 15 de julho."
    )


def test_common_window():
    result = tensions_with(EVA)
    assert result.key_constraints[-1] == KeyConstraint(
        "common-dates", "A janela comum de datas é de 10 a 18 de julho."
    )
    assert [pair.status for pair in result.pairs].count("conflict") == 1
