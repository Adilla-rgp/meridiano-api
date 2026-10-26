# Catálogo de destinos do MVP: os quatro da Viagem de julho, com os mesmos
# custos do motor (tests/fixtures.py) e dos mocks do front
# (meridiano/src/mocks/destinations.ts). tests/api/test_seed.py confere.
#
# O ritmo é definido à mão; pace_note diz por quê.

COST_SOURCE = "Estimativa própria: passagem ida e volta e hospedagem por noite, base julho de 2026"

CATALOG: list[dict] = [
    {
        "id": "dest-lencois",
        "name": "Lençóis Maranhenses",
        "state": "MA",
        "climate": "hot",
        "pace": "relaxed",
        "pace_note": (
            "Dias organizados em torno de passeios às lagoas, com longos intervalos de descanso; "
            "quase não há vida noturna."
        ),
        "fixed_cost": 360,
        "nightly_cost": 115,
        "cost_source": COST_SOURCE,
        "tags": ["praia", "dunas", "natureza"],
    },
    {
        "id": "dest-jericoacoara",
        "name": "Jericoacoara",
        "state": "CE",
        "climate": "hot",
        "pace": "intense",
        "pace_note": "Esportes de vento durante o dia e vida noturna movimentada na vila todas as noites.",
        "fixed_cost": 370,
        "nightly_cost": 120,
        "cost_source": COST_SOURCE,
        "tags": ["praia", "vida noturna", "esportes"],
    },
    {
        "id": "dest-chapada",
        "name": "Chapada Diamantina",
        "state": "BA",
        "climate": "cold",
        "pace": "balanced",
        "pace_note": (
            "Trilhas exigentes de dia, mas noites calmas na cidade; dá para alternar dias puxados e leves."
        ),
        "fixed_cost": 320,
        "nightly_cost": 110,
        "cost_source": COST_SOURCE,
        "tags": ["serra", "trilhas", "cachoeiras"],
    },
    {
        "id": "dest-paraty",
        "name": "Paraty",
        "state": "RJ",
        "climate": "mild",
        "pace": "relaxed",
        "pace_note": (
            "Centro histórico para caminhar sem pressa, passeios de barco e gastronomia; "
            "poucas atividades físicas."
        ),
        "fixed_cost": 480,
        "nightly_cost": 150,
        "cost_source": COST_SOURCE,
        "tags": ["praia", "centro histórico", "gastronomia"],
    },
]
