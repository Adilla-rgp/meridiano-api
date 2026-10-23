from datetime import date

# "Viagem de julho" de demonstração: o mesmo grupo dos mocks do front
# (planner-vite/src/mocks/trip-july.ts) e dos testes do motor (tests/fixtures.py).
# Ana organiza; Ana, Bruno e Carla já responderam; Eva e Diego ainda não.
# Os resumos das restrições vêm do motor ao salvar. tests/api/test_seed.py
# confere que as restrições são as mesmas de tests/fixtures.py.

TRIP = {
    "title": "Viagem de julho",
    "organizer_name": "Ana",
    "destination_ids": ["dest-lencois", "dest-jericoacoara", "dest-chapada", "dest-paraty"],
    "date_window_start": date(2027, 7, 5),
    "date_window_end": date(2027, 7, 26),
    "nights": 6,
    "alpha": 0.5,
}

#: Convidados, além de quem organiza, na ordem do convite.
GUESTS = ["Bruno", "Carla", "Eva", "Diego"]

#: Restrições salvas, por nome.
RESPONSES: dict[str, dict] = {
    "Ana": {
        "raw_text": "Topo qualquer data dentro da janela. Queria muito os Lençóis, praia de preferência.",
        "hard": [],
        "soft": [
            {
                "id": "ana-s1",
                "kind": "prefer_destination",
                "destination_ids": ["dest-lencois"],
                "weight": 0.8,
            },
            {"id": "ana-s2", "kind": "prefer_tags", "tags": ["praia"], "weight": 0.5},
        ],
    },
    "Bruno": {
        "raw_text": "Só consigo de 8 a 18 de julho. Quero praia e agito: Jeri seria perfeito, Paraty também.",
        "hard": [{"id": "bruno-h1", "kind": "date_range", "start": "2027-07-08", "end": "2027-07-18"}],
        "soft": [
            {
                "id": "bruno-s1",
                "kind": "prefer_destination",
                "destination_ids": ["dest-jericoacoara", "dest-paraty"],
                "weight": 0.9,
            },
            {"id": "bruno-s2", "kind": "prefer_tags", "tags": ["praia"], "weight": 0.6},
            {"id": "bruno-s3", "kind": "pace", "pace": "intense", "weight": 0.6},
        ],
    },
    "Carla": {
        "raw_text": "Prefiro serra, a Chapada seria ótima. Ritmo tranquilo, por favor.",
        "hard": [],
        "soft": [
            {
                "id": "carla-s1",
                "kind": "prefer_destination",
                "destination_ids": ["dest-chapada"],
                "weight": 0.9,
            },
            {"id": "carla-s2", "kind": "prefer_tags", "tags": ["serra"], "weight": 0.6},
            {"id": "carla-s3", "kind": "pace", "pace": "relaxed", "weight": 0.7},
        ],
    },
}
