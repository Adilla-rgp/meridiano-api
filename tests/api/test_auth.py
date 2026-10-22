from sqlalchemy import select

from app import models
from app.security import hash_token
from tests.api.conftest import ADMIN, INVITE, create_july_trip

# Autenticação do MVP: admin_token no cabeçalho para o organizador, invite_token
# para cada convidado. O banco guarda só o hash dos tokens.


def test_organizer_routes_require_the_admin_token(client, july):
    routes = [
        ("get", f"/trips/{july.id}"),
        ("get", f"/trips/{july.id}/tensions"),
        ("post", f"/trips/{july.id}/plans"),
        ("post", f"/trips/{july.id}/members"),
        ("post", f"/trips/{july.id}/members/{july.member_ids['Eva']}/invite"),
    ]
    other = create_july_trip(client)
    for method, url in routes:
        assert getattr(client, method)(url).status_code == 401, url
        assert getattr(client, method)(url, headers={ADMIN: "x" * 43}).status_code == 403, url
        # O token de outra viagem também não vale, nem um token de convite.
        assert getattr(client, method)(url, headers=other.admin).status_code == 403, url
        assert getattr(client, method)(url, headers={ADMIN: july.tokens["Ana"]}).status_code == 403, url


def test_unknown_trip_and_invite(client):
    assert client.get("/trips/nao-existe", headers={ADMIN: "x"}).status_code == 404
    assert client.get("/invite/nao-existe").status_code == 404
    reaction = {"invite_token": "nao-existe", "verdict": "accepted"}
    assert client.post("/plans/nao-existe/reactions", json=reaction).status_code == 404


def test_tokens_are_stored_only_as_hashes(client, july, db):
    trip = db.get(models.Trip, july.id)
    assert trip.admin_token_hash == hash_token(july.admin[ADMIN])
    members = db.scalars(select(models.Member).where(models.Member.trip_id == july.id)).all()
    stored = {member.invite_token_hash for member in members}
    assert stored == {hash_token(token) for token in july.tokens.values()}
    assert not stored & set(july.tokens.values())


def test_tokens_are_only_returned_on_creation(client, july):
    detail = client.get(f"/trips/{july.id}", headers=july.admin).json()
    assert all(member["invite_token"] is None for member in detail["members"])
    invite = client.get(f"/invite/{july.tokens['Bruno']}").json()
    assert invite["member"]["invite_token"] is None
    assert all("invite_token" not in member for member in invite["members"])


def test_reissued_invite_replaces_the_old_one(client, july):
    url = f"/trips/{july.id}/members/{july.member_ids['Eva']}/invite"
    reissued = client.post(url, headers=july.admin).json()
    assert reissued["invite_token"] and reissued["invite_token"] != july.tokens["Eva"]
    assert client.get(f"/invite/{july.tokens['Eva']}").status_code == 404
    assert client.get(f"/invite/{reissued['invite_token']}").json()["member"]["display_name"] == "Eva"


def test_plans_read_by_guest_of_another_trip(client, july):
    round_number = client.post(f"/trips/{july.id}/plans", headers=july.admin).json()["round"]
    other = create_july_trip(client)
    url = f"/trips/{july.id}/plans"
    assert client.get(url, params={"round": round_number}).status_code == 401
    response = client.get(url, params={"round": round_number}, headers={INVITE: other.tokens["Bruno"]})
    assert response.status_code == 403


def test_guest_cannot_react_to_a_plan_of_another_trip(client, july):
    plan_id = client.post(f"/trips/{july.id}/plans", headers=july.admin).json()["recommended_plan_id"]
    other = create_july_trip(client)
    reaction = {"invite_token": other.tokens["Bruno"], "verdict": "accepted"}
    assert client.post(f"/plans/{plan_id}/reactions", json=reaction).status_code == 404
