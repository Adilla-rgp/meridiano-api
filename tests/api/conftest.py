import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.cli import seed_catalog
from app.main import create_app
from app.seed.july_trip import RESPONSES
from app.settings import Settings

# Testes de API contra um PostgreSQL de verdade (JSONB, ARRAY, ON CONFLICT):
# um container do testcontainers por sessão de testes, com as migrações do
# Alembic e o catálogo. Para usar um banco já existente, defina
# TEST_DATABASE_URL (ele é apagado a cada teste).

ROOT = Path(__file__).resolve().parents[2]
ADMIN = "X-Admin-Token"
INVITE = "X-Invite-Token"

#: Texto livre de Eva; a interpretação por regras dá as mesmas restrições de tests/fixtures.py.
EVA_TEXT = "Só posso de 10 a 20 de julho, no máximo R$ 1.100 tudo incluso. Não curto frio. Ritmo tranquilo."
#: Diego só pode viajar 3 noites: com 6 noites fixadas, nada é viável.
DIEGO_TEXT = "Só consigo de 12 a 15 de julho, depois tenho prova."


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as error:  # noqa: BLE001 — qualquer falha aqui é "sem Docker"
        pytest.skip(f"Sem Docker para subir o banco de teste: {error}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with Session(engine) as session:
        seed_catalog(session)
        session.commit()
    engine.dispose()
    return database_url


@pytest.fixture
def settings(migrated: str) -> Settings:
    return Settings(_env_file=None, database_url=migrated, front_base_url="http://front.test")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    engine = app.state.sessionmaker.kw["bind"]
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE trips CASCADE"))
    engine.dispose()


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """Sessão direta no banco, para conferir o que foi gravado."""
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        yield session


@dataclass
class TripHandle:
    """Uma viagem criada pela API, com os tokens que só a criação devolve."""

    id: str
    admin: dict[str, str]
    tokens: dict[str, str] = field(default_factory=dict)
    member_ids: dict[str, str] = field(default_factory=dict)

    def invite(self, name: str) -> dict[str, str]:
        return {INVITE: self.tokens[name]}


def create_july_trip(client: TestClient) -> TripHandle:
    """Viagem de julho pela API: Ana organiza, convida os outros 4, e Ana, Bruno e Carla respondem."""
    response = client.post(
        "/trips",
        json={
            "title": "Viagem de julho",
            "organizer_name": "Ana",
            "destination_ids": ["dest-lencois", "dest-jericoacoara", "dest-chapada", "dest-paraty"],
            "date_window_start": "2027-07-05",
            "date_window_end": "2027-07-26",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    trip = TripHandle(created["id"], {ADMIN: created["admin_token"]})
    [organizer] = created["members"]
    trip.tokens["Ana"] = organizer["invite_token"]
    trip.member_ids["Ana"] = organizer["id"]

    response = client.post(
        f"/trips/{trip.id}/members",
        json={"display_names": ["Bruno", "Carla", "Eva", "Diego"]},
        headers=trip.admin,
    )
    assert response.status_code == 201, response.text
    for member in response.json():
        trip.tokens[member["display_name"]] = member["invite_token"]
        trip.member_ids[member["display_name"]] = member["id"]

    for name, body in RESPONSES.items():
        saved = client.put(f"/invite/{trip.tokens[name]}/constraints", json=body)
        assert saved.status_code == 200, saved.text
    return trip


def respond_with_text(client: TestClient, trip: TripHandle, name: str, raw_text: str) -> dict:
    """Interpreta o texto livre e confirma a interpretação sem mudanças, como na tela Responder."""
    parsed = client.post(f"/invite/{trip.tokens[name]}/constraints/parse", json={"raw_text": raw_text})
    assert parsed.status_code == 200, parsed.text
    body = {key: parsed.json()[key] for key in ("raw_text", "hard", "soft")}
    saved = client.put(f"/invite/{trip.tokens[name]}/constraints", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()


@pytest.fixture
def july(client: TestClient) -> TripHandle:
    return create_july_trip(client)
