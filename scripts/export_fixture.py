"""
Roda o motor na Viagem de julho, antes e depois da resposta de Eva, e grava o
resultado em JSON no formato do contrato do front (planner-vite/src/types/api.ts).
Os mocks do front leem esse arquivo: o motor é a fonte dos números.

    python -m scripts.export_fixture                       # fixtures/july-trip.json
    python -m scripts.export_fixture --out ../planner-vite/src/mocks/fixtures/july-trip.json

Cada rodada traz os planos sem id, trip_id e round, que o front (ou a API) atribui
ao criar a rodada. Também vão os dados de entrada do motor (catálogo e restrições),
para o front conferir que os mocks dele são os mesmos.
"""

import argparse
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from engine import run
from engine.models import (
    BlockingLimit,
    Budget,
    DateRange,
    EngineResult,
    ExcludeClimate,
    ExcludedDestination,
    ExcludeDestination,
    HardConstraint,
    Member,
    MemberLimit,
    PlanResult,
    PreferClimate,
    PreferDestination,
    PreferPace,
    PreferTags,
    SoftConstraint,
    TripInput,
)
from engine.privacy import limits_for_member
from tests.fixtures import EVA, JULY_TRIP

TRIP_ID = "trip-julho"
DEFAULT_OUT = Path("fixtures/july-trip.json")
#: Limites violados por plano devolvido: o motor só devolve planos com zero.
VIOLATED_LIMITS = 0


def _iso(value: date) -> str:
    return value.isoformat()


def _hard(item: HardConstraint) -> dict:
    match item:
        case DateRange():
            return {"id": item.id, "kind": "date_range", "start": _iso(item.start), "end": _iso(item.end)}
        case Budget():
            return {
                "id": item.id,
                "kind": "budget",
                "max_per_person": item.max_per_person,
                "all_inclusive": item.all_inclusive,
            }
        case ExcludeClimate():
            return {"id": item.id, "kind": "exclude_climate", "climates": sorted(item.climates)}
        case ExcludeDestination():
            return {
                "id": item.id,
                "kind": "exclude_destination",
                "destination_ids": sorted(item.destination_ids),
            }


def _soft(item: SoftConstraint) -> dict:
    match item:
        case PreferPace():
            return {"id": item.id, "kind": "pace", "pace": item.pace, "weight": item.weight}
        case PreferClimate():
            return {
                "id": item.id,
                "kind": "prefer_climate",
                "climates": sorted(item.climates),
                "weight": item.weight,
            }
        case PreferDestination():
            return {
                "id": item.id,
                "kind": "prefer_destination",
                "destination_ids": list(item.destination_ids),
                "weight": item.weight,
            }
        case PreferTags():
            return {"id": item.id, "kind": "prefer_tags", "tags": list(item.tags), "weight": item.weight}


def _member(member: Member) -> dict:
    return {
        "member_id": member.id,
        "hard": [_hard(c) for c in member.hard],
        "soft": [_soft(c) for c in member.soft],
    }


def _plan(plan: PlanResult, result: EngineResult) -> dict:
    return {
        "destination_id": plan.destination_id,
        "variant_label": plan.variant_label,
        "start_date": _iso(plan.start_date),
        "end_date": _iso(plan.end_date),
        "est_cost_per_person": plan.est_cost_per_person,
        "score": plan.score,
        "alpha": result.alpha,
        "alternatives_evaluated": result.alternatives_evaluated,
        "violated_limits": VIOLATED_LIMITS,
        "per_member_scores": [
            {
                "member_id": item.member_id,
                "score": item.score,
                "has_preferences": item.has_preferences,
                "best_possible": item.best_possible,
            }
            for item in plan.per_member_scores
        ],
        "explanation": [{"member_id": item.member_id, "text": item.text} for item in plan.explanation],
    }


def _excluded(item: ExcludedDestination) -> dict:
    return {
        "destination_id": item.destination_id,
        "reason": item.reason,
        "limits": [{"member_id": ref.member_id, "kind": ref.kind} for ref in item.limits],
        "best_score": item.best_score,
    }


def _blocking(item: BlockingLimit) -> dict:
    return {
        "member_id": item.member_id,
        "kind": item.kind,
        "eliminated_candidates": item.eliminated_candidates,
    }


def _member_limit(item: MemberLimit) -> dict:
    return {
        "constraint_id": item.constraint_id,
        "kind": item.kind,
        "eliminated_destination_ids": list(item.eliminated_destination_ids),
    }


def _round(trip: TripInput) -> dict:
    result = run(trip)
    return {
        "responded_member_ids": sorted(member.id for member in trip.members),
        "plans": [_plan(plan, result) for plan in result.plans],
        "recommended_index": 0 if result.plans else None,
        "excluded_destinations": [_excluded(item) for item in result.excluded_destinations],
        "blocking_limits": [_blocking(item) for item in result.blocking_limits],
    }


def build() -> dict:
    before = replace(JULY_TRIP, members=tuple(m for m in JULY_TRIP.members if m.id != EVA.id))
    return {
        "generated_by": "planner-api scripts/export_fixture.py",
        "trip_id": TRIP_ID,
        "inputs": {
            "window_start": _iso(JULY_TRIP.window_start),
            "window_end": _iso(JULY_TRIP.window_end),
            "nights": JULY_TRIP.nights,
            "alpha": JULY_TRIP.alpha,
            "destinations": [
                {
                    "id": d.id,
                    "climate": d.climate,
                    "pace": d.pace,
                    "tags": list(d.tags),
                    "fixed_cost": d.fixed_cost,
                    "nightly_cost": d.nightly_cost,
                }
                for d in sorted(JULY_TRIP.destinations, key=lambda item: item.id)
            ],
            "members": [_member(m) for m in sorted(JULY_TRIP.members, key=lambda item: item.id)],
        },
        "rounds": {"before_eva_response": _round(before), "after_eva_response": _round(JULY_TRIP)},
        "member_limits": {
            m.id: [_member_limit(item) for item in limits_for_member(JULY_TRIP, m.id)]
            for m in sorted(JULY_TRIP.members, key=lambda item: item.id)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Gravado em {args.out}")


if __name__ == "__main__":
    main()
