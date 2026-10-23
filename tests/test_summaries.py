from datetime import date

from engine.models import (
    Budget,
    DateRange,
    ExcludeClimate,
    ExcludeDestination,
    PreferClimate,
    PreferDestination,
    PreferPace,
    PreferTags,
)
from engine.summaries import format_date_range, hard_summary, soft_summary
from tests.fixtures import JULY_TRIP

DESTINATIONS = {item.id: item for item in JULY_TRIP.destinations}


def test_date_range():
    assert format_date_range(date(2027, 7, 5), date(2027, 7, 26)) == "5 a 26 de julho"
    assert format_date_range(date(2027, 6, 28), date(2027, 7, 1)) == "28 de junho a 1º de julho"
    summary = hard_summary(DateRange("h1", date(2027, 7, 12), date(2027, 7, 15)), DESTINATIONS)
    assert summary == "Datas entre 12 e 15 de julho"


def test_limits():
    assert hard_summary(Budget("h", 1100, True), DESTINATIONS) == "Até R$ 1.100 por pessoa, tudo incluso"
    assert hard_summary(Budget("h", 800, False), DESTINATIONS) == "Até R$ 800 por pessoa"
    assert hard_summary(ExcludeClimate("h", frozenset({"cold"})), DESTINATIONS) == "Nada de destino frio"
    both = hard_summary(ExcludeClimate("h", frozenset({"cold", "hot"})), DESTINATIONS)
    assert both == "Nada de destino quente ou frio"
    veto = hard_summary(ExcludeDestination("h", frozenset({"dest-paraty"})), DESTINATIONS)
    assert veto == "Sem Paraty"


def test_preferences():
    ordered = PreferDestination("s", ("dest-jericoacoara", "dest-paraty"), 0.9)
    assert soft_summary(ordered, DESTINATIONS) == "Jericoacoara, depois Paraty"
    single = PreferDestination("s", ("dest-lencois",), 0.8)
    assert soft_summary(single, DESTINATIONS) == "Lençóis Maranhenses como primeira opção"
    assert soft_summary(PreferTags("s", ("praia", "serra"), 0.5), DESTINATIONS) == "Prefere praia e serra"
    assert soft_summary(PreferPace("s", "relaxed", 0.6), DESTINATIONS) == "Ritmo tranquilo"
    assert soft_summary(PreferClimate("s", frozenset({"hot"}), 0.6), DESTINATIONS) == "Prefere clima quente"
