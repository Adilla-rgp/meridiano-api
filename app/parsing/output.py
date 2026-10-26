from app import schemas
from app.parsing import ParseContext
from engine import models as engine
from engine.summaries import hard_summary, soft_summary

# Saída comum dos parsers: restrições do motor no formato da API, cada uma com
# o resumo gerado pelo motor (nunca pelo parser).


def to_schema(
    raw_text: str,
    hard: list[engine.HardConstraint],
    soft: list[engine.SoftConstraint],
    context: ParseContext,
) -> schemas.ConstraintsInput:
    """Os itens no formato da API, cada um com o resumo do motor."""
    by_id = {destination.id: destination for destination in context.destinations}
    hard_items = [_hard_json(item) | {"summary": hard_summary(item, by_id)} for item in hard]
    soft_items = [_soft_json(item) | {"summary": soft_summary(item, by_id)} for item in soft]
    return schemas.ConstraintsInput.model_validate(
        {"raw_text": raw_text, "hard": hard_items, "soft": soft_items}
    )


def _hard_json(item: engine.HardConstraint) -> dict:
    match item:
        case engine.DateRange():
            return {"id": item.id, "kind": "date_range", "start": item.start, "end": item.end}
        case engine.Budget():
            return {
                "id": item.id,
                "kind": "budget",
                "max_per_person": item.max_per_person,
                "all_inclusive": item.all_inclusive,
            }
        case engine.ExcludeClimate():
            return {"id": item.id, "kind": "exclude_climate", "climates": sorted(item.climates)}
        case engine.ExcludeDestination():
            return {
                "id": item.id,
                "kind": "exclude_destination",
                "destination_ids": sorted(item.destination_ids),
            }
        case engine.ExcludeTags():
            return {"id": item.id, "kind": "exclude_tags", "tags": sorted(item.tags)}


def _soft_json(item: engine.SoftConstraint) -> dict:
    match item:
        case engine.PreferPace():
            return {"id": item.id, "kind": "pace", "pace": item.pace, "weight": item.weight}
        case engine.PreferClimate():
            return {
                "id": item.id,
                "kind": "prefer_climate",
                "climates": sorted(item.climates),
                "weight": item.weight,
            }
        case engine.PreferDestination():
            return {
                "id": item.id,
                "kind": "prefer_destination",
                "destination_ids": list(item.destination_ids),
                "weight": item.weight,
            }
        case engine.PreferTags():
            return {"id": item.id, "kind": "prefer_tags", "tags": list(item.tags), "weight": item.weight}
