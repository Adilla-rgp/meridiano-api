from datetime import date

import pytest

from engine import run
from engine.candidates import Candidate
from engine.models import (
    Budget,
    DateRange,
    Destination,
    EngineResult,
    Member,
    PreferClimate,
    PreferDestination,
    PreferPace,
    PreferTags,
    TripInput,
)
from engine.scoring import breakdown, destination_match, pace_match

# Critérios de aceite da calibração da satisfação.

BEACH = Destination("dest-beach", "Praia", "hot", "relaxed", ("praia", "natureza"), 300, 100)
MOUNTAIN = Destination("dest-mountain", "Serra", "cold", "intense", ("serra", "trilhas"), 300, 100)


def trip(*members: Member) -> TripInput:
    return TripInput(
        window_start=date(2027, 7, 5),
        window_end=date(2027, 7, 26),
        nights=6,
        alpha=0.5,
        destinations=(BEACH, MOUNTAIN),
        members=members,
    )


def recommended_scores(trip_input: TripInput) -> dict[str, float]:
    result = run(trip_input)
    assert isinstance(result, EngineResult)
    return {item.member_id: item.score for item in result.plans[0].per_member_scores}


def test_no_conflict_keeps_everyone_above_08():
    # Cada um pede coisas diferentes, mas todas cabem no mesmo plano.
    members = (
        Member(
            "mem-a", soft=(PreferDestination("a1", ("dest-beach",), 0.8), PreferTags("a2", ("praia",), 0.5))
        ),
        Member(
            "mem-b", soft=(PreferPace("b1", "relaxed", 0.7), PreferClimate("b2", frozenset({"hot"}), 0.5))
        ),
        Member(
            "mem-c",
            hard=(
                DateRange("c1", date(2027, 7, 8), date(2027, 7, 20)),
                Budget("c2", 1500, all_inclusive=True),
            ),
            soft=(PreferTags("c3", ("natureza",), 0.6),),
        ),
        Member("mem-d", soft=(PreferDestination("d1", ("dest-beach", "dest-mountain"), 0.4),)),
    )
    scores = recommended_scores(trip(*members))
    assert all(score > 0.8 for score in scores.values()), scores


def test_identical_wishes_give_everyone_full_satisfaction():
    wishes = (
        PreferDestination("w1", ("dest-beach",), 0.9),
        PreferTags("w2", ("praia",), 0.6),
        PreferPace("w3", "relaxed", 0.7),
        PreferClimate("w4", frozenset({"hot"}), 0.5),
    )
    members = tuple(Member(f"mem-{name}", soft=wishes) for name in ("a", "b", "c", "d"))
    assert recommended_scores(trip(*members)) == dict.fromkeys(("mem-a", "mem-b", "mem-c", "mem-d"), 1.0)


@pytest.mark.parametrize(
    ("destination_id", "expected"),
    [("dest-beach", 1.0), ("dest-mountain", 0.75), ("dest-other", 0.4)],
)
def test_destination_preference_is_graded(destination_id, expected):
    assert destination_match(destination_id, ("dest-beach", "dest-mountain")) == expected


@pytest.mark.parametrize(
    ("preferred", "destination_pace", "expected"),
    [
        ("relaxed", "relaxed", 1.0),
        ("relaxed", "balanced", 0.5),
        ("relaxed", "intense", 0.0),
        ("balanced", "intense", 0.5),
    ],
)
def test_pace_match(preferred, destination_pace, expected):
    assert pace_match(destination_pace, preferred) == expected


def test_unmentioned_preferences_do_not_pull_satisfaction_down():
    only_pace = Member("mem-a", soft=(PreferPace("a1", "relaxed", 0.6),))
    standard = Candidate(BEACH, 6, None, date(2027, 7, 10))
    assert breakdown(only_pace, standard, 6).satisfaction == 1.0


def test_tight_budget_never_falls_below_neutral():
    tight = Member("mem-a", hard=(Budget("a1", 900, all_inclusive=True),))
    at_limit = Candidate(BEACH, 6, None, date(2027, 7, 10))  # custa exatamente 900
    assert breakdown(tight, at_limit, 6).satisfaction == 0.5


def test_short_variant_never_raises_satisfaction():
    member = Member("mem-a", soft=(PreferDestination("a1", ("dest-mountain",), 0.9),))
    standard = Candidate(BEACH, 6, None, date(2027, 7, 10))
    short = Candidate(BEACH, 4, "roteiro curto", date(2027, 7, 10))
    assert breakdown(member, short, 6).satisfaction < breakdown(member, standard, 6).satisfaction
