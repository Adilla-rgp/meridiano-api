import pytest

from tests.api.conftest import create_july_trip

TRIP = {
    "title": "Feriado",
    "organizer_name": "Ana",
    "destination_ids": ["dest-paraty", "dest-lencois"],
    "date_window_start": "2027-07-05",
    "date_window_end": "2027-07-26",
}


@pytest.mark.parametrize(
    "change",
    [
        {"destination_ids": ["dest-paraty"]},
        {"destination_ids": ["dest-paraty", "dest-paraty"]},
        {"destination_ids": ["dest-paraty", "dest-lencois", "dest-chapada", "dest-jericoacoara", "dest-x"]},
        {"date_window_end": "2027-07-08"},
        {"alpha": 1.5},
        {"title": ""},
        {"organizer_name": " "},
    ],
)
def test_invalid_trip(client, change):
    assert client.post("/trips", json=TRIP | change).status_code == 422


def test_destination_outside_the_catalog(client):
    response = client.post("/trips", json=TRIP | {"destination_ids": ["dest-paraty", "dest-atlantida"]})
    assert response.status_code == 422
    assert response.json()["detail"] == "Destino fora do catálogo: dest-atlantida."


def test_at_most_eight_members(client, july):
    response = client.post(
        f"/trips/{july.id}/members", json={"display_names": ["F", "G", "H", "I"]}, headers=july.admin
    )
    assert response.status_code == 422
    ok = client.post(f"/trips/{july.id}/members", json={"display_names": ["F", "G", "H"]}, headers=july.admin)
    assert ok.status_code == 201


@pytest.mark.parametrize(
    "items",
    [
        {"hard": [{"id": "h1", "kind": "date_range", "start": "2027-07-20", "end": "2027-07-10"}]},
        {"hard": [{"id": "h1", "kind": "budget", "max_per_person": -1, "all_inclusive": True}]},
        {"soft": [{"id": "s1", "kind": "pace", "pace": "relaxed", "weight": 2}]},
        {"soft": [{"id": "s1", "kind": "pace", "pace": "lento", "weight": 0.5}]},
        {"hard": [{"id": "h1", "kind": "vibe"}]},
        {
            "soft": [
                {"id": "x", "kind": "pace", "pace": "relaxed", "weight": 0.5},
                {"id": "x", "kind": "pace", "pace": "intense", "weight": 0.5},
            ]
        },
        {
            "soft": [
                {"id": "s1", "kind": "prefer_destination", "destination_ids": ["dest-noronha"], "weight": 0.5}
            ]
        },
    ],
)
def test_invalid_constraints(client, july, items):
    body = {"raw_text": "texto", "hard": [], "soft": []} | items
    assert client.put(f"/invite/{july.tokens['Eva']}/constraints", json=body).status_code == 422


def test_missing_summaries_come_from_the_engine(client, july):
    body = {
        "raw_text": "texto",
        "hard": [{"id": "h1", "kind": "exclude_destination", "destination_ids": ["dest-paraty"]}],
        "soft": [
            {
                "id": "s1",
                "kind": "prefer_destination",
                "destination_ids": ["dest-chapada", "dest-lencois"],
                "weight": 0.5,
            }
        ],
    }
    saved = client.put(f"/invite/{july.tokens['Eva']}/constraints", json=body).json()
    assert saved["hard"][0]["summary"] == "Sem Paraty"
    assert saved["soft"][0]["summary"] == "Chapada Diamantina, depois Lençóis Maranhenses"


def test_saves_a_tag_limit(client, july):
    body = {"raw_text": "não quero praia", "hard": [{"id": "h1", "kind": "exclude_tags", "tags": ["praia"]}]}
    saved = client.put(f"/invite/{july.tokens['Eva']}/constraints", json=body | {"soft": []}).json()
    assert saved["hard"] == [
        {"id": "h1", "summary": "Nada de praia", "kind": "exclude_tags", "tags": ["praia"]}
    ]


def test_parse_needs_some_text(client):
    trip = create_july_trip(client)
    response = client.post(f"/invite/{trip.tokens['Eva']}/constraints/parse", json={"raw_text": "oi"})
    assert response.status_code == 422


def test_reaction_comment_rules(client, july):
    plan_id = client.post(f"/trips/{july.id}/plans", headers=july.admin).json()["recommended_plan_id"]
    url = f"/plans/{plan_id}/reactions"
    token = july.tokens["Carla"]
    reservation = client.post(url, json={"invite_token": token, "verdict": "accepted_with_reservation"})
    assert reservation.json()["detail"] == "Conte qual é a sua ressalva."
    accepted = client.post(
        url, json={"invite_token": token, "verdict": "accepted", "comment": "ignorado"}
    ).json()
    assert accepted["comment"] is None
