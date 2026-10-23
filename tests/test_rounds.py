from datetime import date

from engine.models import DateRange, ExcludeDestination, Member, PreferDestination, PreferPace
from engine.rounds import is_agreed, revise
from tests.fixtures import BRUNO

# Regras entre rodadas: o motivo de uma recusa entra nas restrições e a viagem fecha.


def test_revise_adds_limits_and_replaces_preferences_of_the_same_kind():
    added = Member(
        "mem-bruno",
        hard=(ExcludeDestination("r2-h1", frozenset({"dest-lencois"})),),
        soft=(PreferPace("r2-s1", "relaxed", 0.6),),
    )
    revised = revise(BRUNO, added)
    assert revised.hard == (
        DateRange("bruno-h1", date(2027, 7, 8), date(2027, 7, 18)),
        ExcludeDestination("r2-h1", frozenset({"dest-lencois"})),
    )
    # O ritmo novo substitui o anterior; as outras preferências continuam.
    assert [item.id for item in revised.soft] == ["bruno-s1", "bruno-s2", "r2-s1"]
    assert (revised.id, revised.position) == (BRUNO.id, BRUNO.position)


def test_revise_with_nothing_added_keeps_everything():
    assert revise(BRUNO, Member(BRUNO.id)) == BRUNO


def test_revise_without_previous_constraints():
    added = Member("mem-x", soft=(PreferDestination("r1-s1", ("dest-paraty",), 0.9),))
    assert revise(Member("mem-x", position=3), added) == Member("mem-x", soft=added.soft, position=3)


def test_agreed_when_every_respondent_accepts_the_recommended_plan():
    respondents = ["a", "b", "c"]
    assert is_agreed(respondents, {"a": "accepted", "b": "accepted_with_reservation", "c": "accepted"})
    assert not is_agreed(respondents, {"a": "accepted", "b": "accepted"})
    assert not is_agreed(respondents, {"a": "accepted", "b": "accepted", "c": "rejected"})


def test_a_rejection_from_someone_who_did_not_respond_keeps_the_trip_open():
    assert not is_agreed(["a"], {"a": "accepted", "z": "rejected"})
    assert is_agreed(["a"], {"a": "accepted", "z": "accepted"})


def test_no_respondents_is_never_agreed():
    assert not is_agreed([], {})
