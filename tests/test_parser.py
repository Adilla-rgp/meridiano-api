from datetime import date

import pytest

from app.parsing import ParseContext, get_parser
from app.parsing.rules import RuleBasedParser
from tests.fixtures import JULY_TRIP

CONTEXT = ParseContext(
    window_start=JULY_TRIP.window_start,
    window_end=JULY_TRIP.window_end,
    nights=JULY_TRIP.nights,
    destinations=JULY_TRIP.destinations,
)


def parse(text: str) -> dict:
    result = RuleBasedParser().parse(text, CONTEXT).model_dump()
    return {"hard": result["hard"], "soft": result["soft"]}


def kinds(text: str) -> list[str]:
    result = parse(text)
    return [item["kind"] for item in result["hard"] + result["soft"]]


def test_eva_from_the_visual_reference():
    result = parse(
        "Só posso de 10 a 20 de julho, no máximo R$ 1.100 tudo incluso. Não curto frio. Ritmo tranquilo."
    )
    assert result["hard"] == [
        {
            "id": "h1",
            "summary": "Datas entre 10 e 20 de julho",
            "kind": "date_range",
            "start": date(2027, 7, 10),
            "end": date(2027, 7, 20),
        },
        {
            "id": "h2",
            "summary": "Até R$ 1.100 por pessoa, tudo incluso",
            "kind": "budget",
            "max_per_person": 1100,
            "all_inclusive": True,
        },
        {"id": "h3", "summary": "Nada de destino frio", "kind": "exclude_climate", "climates": ["cold"]},
    ]
    assert result["soft"] == [
        {"id": "s1", "summary": "Ritmo tranquilo", "kind": "pace", "pace": "relaxed", "weight": 0.6},
    ]


@pytest.mark.parametrize(
    ("text", "value", "all_inclusive"),
    [
        ("não curto frio, no máximo uns 800 conto", 800, False),
        ("tenho 1,5 mil pra gastar com tudo", 1500, True),
        ("orçamento de até 950", 950, False),
        ("R$1200", 1200, False),
    ],
)
def test_budget(text, value, all_inclusive):
    [budget] = [item for item in parse(text)["hard"] if item["kind"] == "budget"]
    assert (budget["max_per_person"], budget["all_inclusive"]) == (value, all_inclusive)


@pytest.mark.parametrize("text", ["no máximo 3 noites", "vamos em 4 pessoas", "dia 12 de julho tenho prova"])
def test_numbers_that_are_not_money(text):
    assert "budget" not in kinds(text)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("Só consigo de 12 a 15 de julho", date(2027, 7, 12), date(2027, 7, 15)),
        ("entre 28 de junho e 3 de julho", date(2027, 6, 28), date(2027, 7, 3)),
        ("posso de 1º a 10 de julho", date(2027, 7, 1), date(2027, 7, 10)),
        ("livre 08/07 a 18/07", date(2027, 7, 8), date(2027, 7, 18)),
    ],
)
def test_dates(text, start, end):
    [item] = [item for item in parse(text)["hard"] if item["kind"] == "date_range"]
    assert (item["start"], item["end"]) == (start, end)


def test_destinations_in_order_and_vetoes():
    result = parse("Paraty seria perfeito, depois Lençóis. Chapada não, por favor.")
    [veto] = result["hard"]
    assert veto["destination_ids"] == ["dest-chapada"] and veto["summary"] == "Sem Chapada Diamantina"
    [prefer] = [item for item in result["soft"] if item["kind"] == "prefer_destination"]
    assert prefer["destination_ids"] == ["dest-paraty", "dest-lencois"]
    assert prefer["summary"] == "Paraty, depois Lençóis Maranhenses"


def test_tags_climate_and_pace():
    result = parse("Prefiro serra e cachoeira, adoro calor. Quero muito agito!")
    by_kind = {item["kind"]: item for item in result["soft"]}
    assert by_kind["prefer_tags"]["tags"] == ["serra", "cachoeiras"]
    assert by_kind["prefer_climate"]["climates"] == ["hot"]
    assert (by_kind["pace"]["pace"], by_kind["pace"]["weight"]) == ("intense", 0.8)


def test_negated_tag_becomes_a_limit():
    result = parse("Não quero praia dessa vez, mas curto trilha.")
    assert result["hard"] == [
        {"id": "h1", "summary": "Nada de praia", "kind": "exclude_tags", "tags": ["praia"]},
    ]
    assert [item["tags"] for item in result["soft"] if item["kind"] == "prefer_tags"] == [["trilhas"]]


def test_negated_pace_flips():
    [pace] = parse("nada muito parado, por favor")["soft"]
    assert pace["pace"] == "intense"


def test_nothing_understood():
    assert parse("Tanto faz pra mim, vou aonde a galera for.") == {"hard": [], "soft": []}


def test_parser_is_chosen_by_setting():
    assert isinstance(get_parser("rules"), RuleBasedParser)
    with pytest.raises(ValueError):
        get_parser("llm")
