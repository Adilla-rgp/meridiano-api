import random
from dataclasses import replace
from datetime import date

import pytest

from engine import run
from engine.candidates import generate_candidates, violations
from engine.models import (
    BlockingLimit,
    Budget,
    DateRange,
    EngineInputError,
    EngineResult,
    ExcludedDestination,
    LimitRef,
    Member,
)
from tests.fixtures import ANA, BRUNO, CARLA, EVA, JULY_TRIP, trip_with


def plans_of(result) -> EngineResult:
    assert isinstance(result, EngineResult)
    return result


def scores_by_member(plan) -> dict[str, float]:
    return {item.member_id: item.score for item in plan.per_member_scores}


def texts_by_member(plan) -> dict[str, str]:
    return {item.member_id: item.text for item in plan.explanation}


# Viagem de julho


def test_recommends_lencois_for_july_trip():
    result = plans_of(run(JULY_TRIP))
    recommended = result.plans[0]
    assert (recommended.destination_id, recommended.variant_label) == ("dest-lencois", None)
    assert (recommended.start_date, recommended.end_date) == (date(2027, 7, 10), date(2027, 7, 16))
    assert recommended.est_cost_per_person == 1050


def test_july_trip_alternatives_and_order():
    result = plans_of(run(JULY_TRIP))
    assert [(plan.destination_id, plan.variant_label) for plan in result.plans] == [
        ("dest-lencois", None),
        ("dest-lencois", "roteiro curto"),
        ("dest-paraty", "roteiro curto"),
    ]
    assert [plan.score for plan in result.plans] == sorted(
        (plan.score for plan in result.plans), reverse=True
    )


def test_july_trip_member_scores():
    # Regressão: números da calibração de 21/10/2026.
    plan = plans_of(run(JULY_TRIP)).plans[0]
    assert scores_by_member(plan) == {
        "mem-ana": 1.0,
        "mem-bruno": 0.4571,
        "mem-carla": 0.4818,
        "mem-eva": 0.8244,
    }
    assert plan.score == 0.574
    assert [plan.score for plan in plans_of(run(JULY_TRIP)).plans] == [0.574, 0.5363, 0.4995]


def test_july_trip_explanations():
    texts = texts_by_member(plans_of(run(JULY_TRIP)).plans[0])
    assert texts == {
        "mem-ana": "Ganhou o destino que indicou, com praia.",
        "mem-bruno": (
            "Ganhou um destino de praia. Abriu mão dos destinos que indicou e do ritmo agitado que pediu."
        ),
        "mem-carla": (
            "Ganhou o ritmo tranquilo que pediu. Abriu mão do destino que indicou e de um destino de serra."
        ),
        "mem-eva": "Ganhou o ritmo tranquilo que pediu.",
    }


def test_short_variant_explains_lost_days():
    short = plans_of(run(JULY_TRIP)).plans[1]
    assert texts_by_member(short)["mem-ana"] == (
        "Ganhou o destino que indicou, com praia. Abriu mão de 2 dias de viagem."
    )
    assert (
        texts_by_member(short)["mem-eva"]
        == "Ganhou o ritmo tranquilo que pediu. Abriu mão de 2 dias de viagem."
    )


def test_second_listed_destination_is_a_partial_gain():
    paraty = plans_of(run(JULY_TRIP)).plans[2]
    assert texts_by_member(paraty)["mem-bruno"].startswith("Ganhou um dos destinos que indicou, com praia.")


# Propriedades


def test_is_deterministic_regardless_of_input_order():
    shuffled = list(JULY_TRIP.members), list(JULY_TRIP.destinations)
    random.Random(7).shuffle(shuffled[0])
    random.Random(7).shuffle(shuffled[1])
    assert run(JULY_TRIP) == run(trip_with(members=tuple(shuffled[0]), destinations=tuple(shuffled[1])))


def test_returned_plans_never_violate_limits():
    result = plans_of(run(JULY_TRIP))
    by_key = {(c.destination.id, c.variant_label, c.start): c for c in generate_candidates(JULY_TRIP)}
    for plan in result.plans:
        candidate = by_key[(plan.destination_id, plan.variant_label, plan.start_date)]
        assert violations(candidate, JULY_TRIP.members) == []
    assert "dest-chapada" not in {plan.destination_id for plan in result.plans}


def test_explanations_never_reveal_budget():
    result = plans_of(run(JULY_TRIP))
    for plan in result.plans:
        for item in plan.explanation:
            assert "R$" not in item.text
            assert "1100" not in item.text and "1.100" not in item.text


def test_member_without_preferences_is_neutral():
    result = plans_of(run(trip_with(members=(ANA, Member("mem-diego")))))
    standard = next(plan for plan in result.plans if plan.variant_label is None)
    assert scores_by_member(standard)["mem-diego"] == 0.5
    assert texts_by_member(standard)["mem-diego"] == "Não indicou preferências."


def test_alpha_one_protects_worst_off():
    result = plans_of(run(trip_with(alpha=1.0)))
    for plan in result.plans:
        assert plan.score == min(scores_by_member(plan).values())


def test_counts_every_generated_candidate():
    assert plans_of(run(JULY_TRIP)).alternatives_evaluated == len(list(generate_candidates(JULY_TRIP)))


# Sem plano viável


def test_member_who_can_only_travel_three_nights_blocks_every_plan():
    # Seis noites fixadas, roteiro curto de quatro: três noites não cabem em nenhum.
    three_nights = Member("mem-diego", hard=(DateRange("diego-h1", date(2027, 7, 12), date(2027, 7, 15)),))
    result = run(trip_with(members=(ANA, BRUNO, CARLA, EVA, three_nights)))

    assert result.plans == ()
    total = result.alternatives_evaluated
    assert result.blocking_limits[0] == BlockingLimit("mem-diego", "date_range", total)
    assert [item.eliminated_candidates for item in result.blocking_limits] == sorted(
        (item.eliminated_candidates for item in result.blocking_limits), reverse=True
    )
    assert {item.destination_id for item in result.excluded_destinations} == {
        "dest-chapada",
        "dest-jericoacoara",
        "dest-lencois",
        "dest-paraty",
    }
    assert all(item.reason == "limit" for item in result.excluded_destinations)


def test_budget_blocking_limit_has_no_member():
    broke = Member("mem-diego", hard=(Budget("diego-h1", 500, all_inclusive=True),))
    result = run(trip_with(members=(ANA, BRUNO, EVA, broke)))
    assert result.plans == ()
    # Os orçamentos de Eva e de Diego viram um só item, sem identificar ninguém.
    budget = [item for item in result.blocking_limits if item.kind == "budget"]
    assert budget == [BlockingLimit(None, "budget", result.alternatives_evaluated)]


def test_feasible_round_has_no_blocking_limits():
    assert plans_of(run(JULY_TRIP)).blocking_limits == ()


# Entrada inválida


@pytest.mark.parametrize(
    "changes",
    [
        {"alpha": 1.5},
        {"nights": 0},
        {"window_end": date(2027, 7, 8)},
        {"members": ()},
        {"destinations": ()},
    ],
)
def test_rejects_invalid_input(changes):
    with pytest.raises(EngineInputError):
        run(trip_with(**changes))


# Quem não declarou preferências


def test_member_without_preferences_stays_out_of_the_score():
    result = plans_of(run(trip_with(members=(ANA, Member("mem-diego")))))
    for plan in result.plans:
        by_member = {item.member_id: item for item in plan.per_member_scores}
        assert by_member["mem-diego"].has_preferences is False
        assert by_member["mem-ana"].has_preferences is True
        # Só Ana conta: com uma pessoa, média e mínimo são a satisfação dela.
        assert plan.score == by_member["mem-ana"].score


def test_nobody_with_preferences_breaks_ties_by_lowest_cost():
    nobody = (Member("mem-a"), Member("mem-b"))
    result = plans_of(run(trip_with(members=nobody)))
    assert [plan.score for plan in result.plans] == [0.0, 0.0, 0.0]
    assert [(plan.destination_id, plan.est_cost_per_person) for plan in result.plans] == [
        ("dest-chapada", 980),
        ("dest-lencois", 1050),
        ("dest-jericoacoara", 1090),
    ]


# Melhor possível


@pytest.mark.parametrize("alpha", [0.0, 0.5, 1.0])
def test_best_possible_is_never_below_any_returned_plan(alpha):
    result = plans_of(run(trip_with(alpha=alpha)))
    for plan in result.plans:
        for item in plan.per_member_scores:
            assert item.best_possible >= item.score


def test_july_trip_best_possible():
    plan = plans_of(run(JULY_TRIP)).plans[0]
    assert {item.member_id: item.best_possible for item in plan.per_member_scores} == {
        "mem-ana": 1.0,
        "mem-bruno": 1.0,  # em Jericoacoara
        "mem-carla": 0.4818,  # a Chapada é vetada pelo limite de clima de Eva
        "mem-eva": 0.9,
    }


# Destinos excluídos


def test_july_trip_excluded_destinations():
    assert plans_of(run(JULY_TRIP)).excluded_destinations == (
        ExcludedDestination("dest-chapada", "limit", (LimitRef("mem-eva", "exclude_climate"),), None),
        ExcludedDestination("dest-jericoacoara", "lower_score", (), 0.3358),
    )


def test_budget_exclusion_names_the_limit_but_not_the_value():
    tighter = replace(EVA, hard=(*EVA.hard[:1], Budget("eva-h2", 1000, all_inclusive=True), *EVA.hard[2:]))
    result = plans_of(run(trip_with(members=(ANA, BRUNO, CARLA, tighter))))
    paraty = next(item for item in result.excluded_destinations if item.destination_id == "dest-paraty")
    assert paraty == ExcludedDestination("dest-paraty", "limit", (LimitRef(None, "budget"),), None)
    assert "1000" not in repr(result.excluded_destinations)
