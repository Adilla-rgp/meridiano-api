"""
Comandos de manutenção:

    python -m app.cli seed-catalog       # cria ou atualiza o catálogo de destinos
    python -m app.cli create-demo-trip   # cria a Viagem de julho e mostra os links

Usam DATABASE_URL (app/settings.py).
"""

import argparse

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import models, queries, schemas, services
from app.db import make_sessionmaker
from app.seed import july_trip
from app.seed.catalog import CATALOG
from app.settings import Settings, get_settings


def seed_catalog(session: Session) -> int:
    """Idempotente: insere os destinos que faltam e atualiza os que já existem."""
    statement = insert(models.CatalogDestination).values(CATALOG)
    columns = {name: statement.excluded[name] for name in CATALOG[0] if name != "id"}
    session.execute(statement.on_conflict_do_update(index_elements=["id"], set_=columns))
    return len(CATALOG)


def create_demo_trip(session: Session) -> tuple[models.Trip, str, dict[str, str]]:
    """A Viagem de julho, com 3 respostas. Devolve a viagem, o admin_token e os convites por nome."""
    data = schemas.CreateTripInput(**july_trip.TRIP)
    trip, admin_token, organizer_token = services.create_trip(session, data)
    tokens = {july_trip.TRIP["organizer_name"]: organizer_token}
    for member, token in services.add_members(session, trip, july_trip.GUESTS):
        tokens[member.display_name] = token

    members = {member.display_name: member for member in queries.trip_members(session, trip.id)}
    for name, response in july_trip.RESPONSES.items():
        services.save_constraints(session, members[name], schemas.ConstraintsInput.model_validate(response))
    return trip, admin_token, tokens


def main(argv: list[str] | None = None, settings: Settings | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["seed-catalog", "create-demo-trip"])
    args = parser.parse_args(argv)
    settings = settings or get_settings()

    with make_sessionmaker(settings.database_url)() as session:
        if args.command == "seed-catalog":
            count = seed_catalog(session)
            session.commit()
            print(f"Catálogo: {count} destinos.")
            return

        trip, admin_token, tokens = create_demo_trip(session)
        session.commit()
        front = settings.front_base_url.rstrip("/")
        print(f"Viagem de julho criada: {trip.id}")
        print(f"Token de administração (cabeçalho X-Admin-Token): {admin_token}")
        print(f"Link de administração: {front}/viagens/{trip.id}/tensoes#admin={admin_token}")
        print("Convites:")
        for name, token in tokens.items():
            print(f"  {name}: {front}/convite/{token}")


if __name__ == "__main__":
    main()
