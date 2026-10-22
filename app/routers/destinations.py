from fastapi import APIRouter
from sqlalchemy import select

from app import convert, models, schemas
from app.deps import SessionDep

router = APIRouter(tags=["catálogo"])

#: Noites usadas no custo estimado do catálogo, antes de existir uma viagem.
CATALOG_NIGHTS = 6


@router.get("/destinations", response_model=list[schemas.Destination])
def list_destinations(session: SessionDep):
    rows = session.scalars(select(models.CatalogDestination).order_by(models.CatalogDestination.name))
    return [convert.destination_schema(row, CATALOG_NIGHTS) for row in rows]
