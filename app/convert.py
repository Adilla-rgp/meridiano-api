from datetime import date

from app import models, schemas
from app.parsing import ParseContext
from engine import models as engine
from engine.summaries import hard_summary, soft_summary

# Conversão entre o banco, os modelos da API e os do motor. Nada aqui decide:
# só troca de formato.


def engine_destination(row: models.CatalogDestination) -> engine.Destination:
    return engine.Destination(
        id=row.id,
        name=row.name,
        climate=row.climate,  # type: ignore[arg-type]
        pace=row.pace,  # type: ignore[arg-type]
        tags=tuple(row.tags),
        fixed_cost=float(row.fixed_cost),
        nightly_cost=float(row.nightly_cost),
    )


def destination_schema(row: models.CatalogDestination, nights: int) -> schemas.Destination:
    return schemas.Destination(
        id=row.id,
        name=row.name,
        state=row.state,
        climate=row.climate,  # type: ignore[arg-type]
        pace=row.pace,  # type: ignore[arg-type]
        fixed_cost=float(row.fixed_cost),
        nightly_cost=float(row.nightly_cost),
        est_cost_per_person=engine_destination(row).cost_for(nights),
        cost_source=row.cost_source,
        tags=list(row.tags),
    )


def engine_hard(item: dict) -> engine.HardConstraint:
    match item["kind"]:
        case "date_range":
            return engine.DateRange(
                item["id"], date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
            )
        case "budget":
            return engine.Budget(item["id"], float(item["max_per_person"]), bool(item["all_inclusive"]))
        case "exclude_climate":
            return engine.ExcludeClimate(item["id"], frozenset(item["climates"]))
        case "exclude_destination":
            return engine.ExcludeDestination(item["id"], frozenset(item["destination_ids"]))
    raise ValueError(f"Limite desconhecido: {item['kind']}")


def engine_soft(item: dict) -> engine.SoftConstraint:
    match item["kind"]:
        case "pace":
            return engine.PreferPace(item["id"], item["pace"], float(item["weight"]))
        case "prefer_climate":
            return engine.PreferClimate(item["id"], frozenset(item["climates"]), float(item["weight"]))
        case "prefer_destination":
            return engine.PreferDestination(item["id"], tuple(item["destination_ids"]), float(item["weight"]))
        case "prefer_tags":
            return engine.PreferTags(item["id"], tuple(item["tags"]), float(item["weight"]))
    raise ValueError(f"Preferência desconhecida: {item['kind']}")


def engine_member(member_id: str, hard: list[dict], soft: list[dict], position: int = 0) -> engine.Member:
    return engine.Member(
        member_id,
        tuple(engine_hard(item) for item in hard),
        tuple(engine_soft(item) for item in soft),
        position,
    )


def trip_input(
    trip: models.Trip, destinations: list[models.CatalogDestination], members: list[engine.Member]
) -> engine.TripInput:
    return engine.TripInput(
        window_start=trip.date_window_start,
        window_end=trip.date_window_end,
        nights=trip.nights,
        alpha=trip.alpha,
        destinations=tuple(engine_destination(row) for row in destinations),
        members=tuple(members),
    )


def parse_context(trip: models.Trip, destinations: list[models.CatalogDestination]) -> ParseContext:
    return ParseContext(
        window_start=trip.date_window_start,
        window_end=trip.date_window_end,
        nights=trip.nights,
        destinations=tuple(engine_destination(row) for row in destinations),
    )


def items_json(items: list[schemas.Item]) -> list[dict]:
    return [item.model_dump(mode="json") for item in items]


def with_summaries(
    data: schemas.ConstraintsInput, destinations: list[models.CatalogDestination]
) -> schemas.ConstraintsInput:
    """Preenche o resumo de cada item que chegou sem um, com o texto do motor."""
    by_id = {row.id: engine_destination(row) for row in destinations}
    hard = [
        item
        if item.summary
        else item.model_copy(update={"summary": hard_summary(engine_hard(as_json), by_id)})
        for item, as_json in zip(data.hard, items_json(data.hard), strict=True)
    ]
    soft = [
        item
        if item.summary
        else item.model_copy(update={"summary": soft_summary(engine_soft(as_json), by_id)})
        for item, as_json in zip(data.soft, items_json(data.soft), strict=True)
    ]
    return data.model_copy(update={"hard": hard, "soft": soft})


def member_limit(item: engine.MemberLimit) -> schemas.MemberLimit:
    return schemas.MemberLimit(
        constraint_id=item.constraint_id,
        kind=item.kind,
        eliminated_destination_ids=list(item.eliminated_destination_ids),
    )
