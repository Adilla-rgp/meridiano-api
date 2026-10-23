from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.ratelimit import RateLimiter
from app.settings import Settings
from tests.api.conftest import create_july_trip

# Limite de requisições por token nas rotas caras: interpretação do texto livre
# (parse e motivo da recusa) e geração de planos.


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_counts_per_token_in_a_sliding_window():
    clock = Clock()
    limiter = RateLimiter(2, window=60, clock=clock)
    limiter.check("a")
    clock.now += 30
    limiter.check("a")
    limiter.check("b")  # outro token tem a própria conta
    with pytest.raises(HTTPException) as error:
        limiter.check("a")
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "30"}
    clock.now += 30  # a primeira requisição saiu da janela
    limiter.check("a")


def test_limit_zero_turns_it_off():
    limiter = RateLimiter(0)
    for _ in range(100):
        limiter.check("a")


@pytest.fixture
def limited(client: TestClient, settings: Settings) -> Iterator[TestClient]:
    """Mesmo banco do client (que limpa as viagens no fim), com limites baixos."""
    app = create_app(settings.model_copy(update={"parse_rate_limit": 2, "plans_rate_limit": 1}))
    with TestClient(app) as test_client:
        yield test_client


def test_parse_route_is_limited_per_invite(limited):
    trip = create_july_trip(limited)
    body = {"raw_text": "Ritmo tranquilo, por favor."}
    eva, diego = (f"/invite/{trip.tokens[name]}/constraints/parse" for name in ("Eva", "Diego"))
    assert [limited.post(eva, json=body).status_code for _ in range(2)] == [200, 200]
    blocked = limited.post(eva, json=body)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["detail"].startswith("Muitas tentativas em pouco tempo.")
    assert limited.post(diego, json=body).status_code == 200
    # Um convite que não existe é recusado antes de contar.
    assert limited.post("/invite/nao-existe/constraints/parse", json=body).status_code == 404


def test_rejection_reason_counts_as_a_parse(limited):
    trip = create_july_trip(limited)
    plans = limited.post(f"/trips/{trip.id}/plans", headers=trip.admin).json()
    url = f"/plans/{plans['recommended_plan_id']}/reactions"
    body = {"invite_token": trip.tokens["Carla"], "verdict": "rejected", "comment": "Lençóis não."}
    assert [limited.post(url, json=body).status_code for _ in range(2)] == [201, 201]
    assert limited.post(url, json=body).status_code == 429
    # Aceitar não passa pela interpretação e não conta.
    accept = {"invite_token": trip.tokens["Carla"], "verdict": "accepted"}
    assert limited.post(url, json=accept).status_code == 201


def test_plan_generation_is_limited_per_admin_token(limited):
    trip = create_july_trip(limited)
    other = create_july_trip(limited)
    assert limited.post(f"/trips/{trip.id}/plans", headers=trip.admin).status_code == 201
    assert limited.post(f"/trips/{trip.id}/plans", headers=trip.admin).status_code == 429
    assert limited.post(f"/trips/{other.id}/plans", headers=other.admin).status_code == 201
    # Sem token válido, a resposta é de autenticação, não de limite.
    assert limited.post(f"/trips/{trip.id}/plans", headers={"X-Admin-Token": "x"}).status_code == 403
