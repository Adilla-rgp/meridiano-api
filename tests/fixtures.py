from dataclasses import replace
from datetime import date

from engine.models import (
    Budget,
    DateRange,
    Destination,
    ExcludeClimate,
    Member,
    PreferDestination,
    PreferPace,
    PreferTags,
    TripInput,
)

# "Viagem de julho", o mesmo grupo dos mocks do front (planner-vite/src/mocks).
# Custos decompostos para bater com os valores de 6 noites do catálogo:
# Lençóis 360 + 6 × 115 = 1050.

LENCOIS = Destination(
    "dest-lencois", "Lençóis Maranhenses", "hot", "relaxed", ("praia", "dunas", "natureza"), 360, 115
)
JERICOACOARA = Destination(
    "dest-jericoacoara", "Jericoacoara", "hot", "intense", ("praia", "vida noturna", "esportes"), 370, 120
)
CHAPADA = Destination(
    "dest-chapada", "Chapada Diamantina", "cold", "balanced", ("serra", "trilhas", "cachoeiras"), 320, 110
)
PARATY = Destination(
    "dest-paraty", "Paraty", "mild", "relaxed", ("praia", "centro histórico", "gastronomia"), 480, 150
)

ANA = Member(
    "mem-ana",
    soft=(
        PreferDestination("ana-s1", ("dest-lencois",), 0.8),
        PreferTags("ana-s2", ("praia",), 0.5),
    ),
    position=0,
)
BRUNO = Member(
    "mem-bruno",
    hard=(DateRange("bruno-h1", date(2027, 7, 8), date(2027, 7, 18)),),
    soft=(
        PreferDestination("bruno-s1", ("dest-jericoacoara", "dest-paraty"), 0.9),
        PreferTags("bruno-s2", ("praia",), 0.6),
        PreferPace("bruno-s3", "intense", 0.6),
    ),
    position=1,
)
CARLA = Member(
    "mem-carla",
    soft=(
        PreferDestination("carla-s1", ("dest-chapada",), 0.9),
        PreferTags("carla-s2", ("serra",), 0.6),
        PreferPace("carla-s3", "relaxed", 0.7),
    ),
    position=2,
)
EVA = Member(
    "mem-eva",
    hard=(
        DateRange("eva-h1", date(2027, 7, 10), date(2027, 7, 20)),
        Budget("eva-h2", 1100, all_inclusive=True),
        ExcludeClimate("eva-h3", frozenset({"cold"})),
    ),
    soft=(PreferPace("eva-s1", "relaxed", 0.6),),
    position=3,
)

#: Diego, na demonstração: só pode viajar de 12 a 15 de julho (3 noites) e não declara preferências.
DIEGO = Member("mem-diego", hard=(DateRange("diego-h1", date(2027, 7, 12), date(2027, 7, 15)),), position=4)

JULY_TRIP = TripInput(
    window_start=date(2027, 7, 5),
    window_end=date(2027, 7, 26),
    nights=6,
    alpha=0.5,
    destinations=(LENCOIS, JERICOACOARA, CHAPADA, PARATY),
    members=(ANA, BRUNO, CARLA, EVA),
)


def trip_with(**changes) -> TripInput:
    return replace(JULY_TRIP, **changes)
