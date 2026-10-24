from evals.run import score_case


def case(hard=(), soft=(), optional=()):
    return {"hard": list(hard), "soft": list(soft), "optional": list(optional)}


def test_budget_range_accepts_any_value_inside():
    expected = case(hard=[{"kind": "budget", "max_per_person": [1000, 1200], "all_inclusive": None}])
    inside = [{"kind": "budget", "max_per_person": 1100, "all_inclusive": False}]
    outside = [{"kind": "budget", "max_per_person": 1500, "all_inclusive": False}]
    correct, invented = score_case(expected, inside)
    assert all(correct.values()) and invented == []
    correct, invented = score_case(expected, outside)
    assert not correct["budget"] and invented == ["budget: 1500, tudo incluso=False"]


def test_wrong_value_counts_as_invented():
    expected = case(hard=[{"kind": "date_range", "start": "2027-07-10", "end": "2027-07-20"}])
    correct, invented = score_case(
        expected, [{"kind": "date_range", "start": "2027-07-10", "end": "2027-07-21"}]
    )
    assert not correct["dates"] and invented == ["dates: ('2027-07-10', '2027-07-21')"]


def test_optional_is_neither_missing_nor_invented():
    expected = case(
        soft=[{"kind": "prefer_tags", "tags": ["vida noturna"]}],
        optional=[{"kind": "pace", "pace": "intense"}],
    )
    with_optional = [{"kind": "prefer_tags", "tags": ["vida noturna"]}, {"kind": "pace", "pace": "intense"}]
    for predicted in (with_optional, with_optional[:1]):
        correct, invented = score_case(expected, predicted)
        assert all(correct.values()) and invented == []


def test_destination_order_does_not_matter():
    expected = case(soft=[{"kind": "prefer_destination", "destination_ids": ["dest-lencois", "dest-paraty"]}])
    predicted = [{"kind": "prefer_destination", "destination_ids": ["dest-paraty", "dest-lencois"]}]
    assert all(score_case(expected, predicted)[0].values())
