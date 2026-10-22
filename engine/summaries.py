from datetime import date

from engine.explain import join_pt
from engine.models import (
    Budget,
    Climate,
    DateRange,
    Destination,
    ExcludeClimate,
    ExcludeDestination,
    HardConstraint,
    PreferClimate,
    PreferDestination,
    PreferPace,
    PreferTags,
    SoftConstraint,
)

# Resumos das restrições: uma frase pronta para exibição, gerada a partir dos
# valores estruturados ("Até R$ 1.100 por pessoa, tudo incluso"). O resumo de
# orçamento traz o valor, então só a própria pessoa o vê (privacy.py).

MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

PACE_SUMMARY = {"relaxed": "Ritmo tranquilo", "balanced": "Ritmo equilibrado", "intense": "Ritmo agitado"}
CLIMATE_ADJECTIVE = {"hot": "quente", "mild": "ameno", "cold": "frio"}
CLIMATE_ORDER: tuple[Climate, ...] = ("hot", "mild", "cold")


def _day(value: date) -> str:
    return "1º" if value.day == 1 else str(value.day)


def format_date_range(start: date, end: date) -> str:
    """ "5 a 26 de julho" ou "28 de junho a 3 de julho", como o front."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{_day(start)} a {_day(end)} de {MONTHS[end.month - 1]}"
    return f"{_day(start)} de {MONTHS[start.month - 1]} a {_day(end)} de {MONTHS[end.month - 1]}"


def format_currency(value: float) -> str:
    """ "R$ 1.100", sem centavos."""
    return "R$ " + f"{round(value):,}".replace(",", ".")


def _or(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} ou {items[-1]}"


def _climates(climates: frozenset[Climate]) -> str:
    return _or([CLIMATE_ADJECTIVE[item] for item in CLIMATE_ORDER if item in climates])


def destination_preference_summary(names: list[str]) -> str:
    """ "Lençóis Maranhenses como primeira opção" ou "Jericoacoara, depois Paraty"."""
    if len(names) == 1:
        return f"{names[0]} como primeira opção"
    return ", depois ".join(names)


def hard_summary(item: HardConstraint, destinations: dict[str, Destination]) -> str:
    match item:
        case DateRange(start=start, end=end):
            return f"Datas entre {format_date_range(start, end).replace(' a ', ' e ', 1)}"
        case Budget(max_per_person=limit, all_inclusive=all_inclusive):
            text = f"Até {format_currency(limit)} por pessoa"
            return f"{text}, tudo incluso" if all_inclusive else text
        case ExcludeClimate(climates=climates):
            return f"Nada de destino {_climates(climates)}"
        case ExcludeDestination(destination_ids=ids):
            names = sorted(destinations[i].name if i in destinations else i for i in ids)
            return f"Sem {' nem '.join(names)}"


def soft_summary(item: SoftConstraint, destinations: dict[str, Destination]) -> str:
    match item:
        case PreferPace(pace=pace):
            return PACE_SUMMARY[pace]
        case PreferClimate(climates=climates):
            return f"Prefere clima {_climates(climates)}"
        case PreferDestination(destination_ids=ids):
            return destination_preference_summary(
                [destinations[i].name if i in destinations else i for i in ids]
            )
        case PreferTags(tags=tags):
            return f"Prefere {join_pt(list(tags))}"
