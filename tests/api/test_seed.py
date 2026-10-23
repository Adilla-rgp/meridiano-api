from sqlalchemy import select

from app import convert, models
from app.cli import create_demo_trip, main, seed_catalog
from app.seed.catalog import CATALOG
from app.seed.july_trip import RESPONSES
from tests.fixtures import ANA, BRUNO, CARLA, JULY_TRIP

# O catálogo e a Viagem de julho de demonstração são os mesmos dados do motor
# (tests/fixtures.py) e, por ele, dos mocks do front.


def test_catalog_matches_the_engine_fixtures(db):
    rows = db.scalars(select(models.CatalogDestination).order_by(models.CatalogDestination.id)).all()
    expected = sorted(JULY_TRIP.destinations, key=lambda item: item.id)
    assert [convert.engine_destination(row) for row in rows] == expected
    assert all(row.pace_note for row in rows)


def test_seed_catalog_is_idempotent(db):
    assert seed_catalog(db) == len(CATALOG)
    db.commit()
    assert db.scalar(select(models.CatalogDestination).where(models.CatalogDestination.id == "dest-paraty"))


def test_demo_responses_match_the_engine_fixtures():
    members = {
        name: convert.engine_member(f"mem-{name.lower()}", body["hard"], body["soft"])
        for name, body in RESPONSES.items()
    }
    assert members == {"Ana": ANA, "Bruno": BRUNO, "Carla": CARLA}


def test_create_demo_trip(client, db, settings, capsys):
    trip, admin_token, tokens = create_demo_trip(db)
    db.commit()
    assert list(tokens) == ["Ana", "Bruno", "Carla", "Eva", "Diego"]
    detail = client.get(f"/trips/{trip.id}", headers={"X-Admin-Token": admin_token}).json()
    assert [m["responded_at"] is not None for m in detail["members"]] == [True, True, True, False, False]
    invite = client.get(f"/invite/{tokens['Bruno']}").json()
    assert [item["summary"] for item in invite["constraints"]["soft"]] == [
        "Jericoacoara, depois Paraty",
        "Prefere praia",
        "Ritmo agitado",
    ]

    main(["create-demo-trip"], settings)
    printed = capsys.readouterr().out
    assert "X-Admin-Token" in printed and "http://front.test/convite/" in printed
