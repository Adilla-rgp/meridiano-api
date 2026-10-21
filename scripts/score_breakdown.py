"""
Decomposição da satisfação de cada pessoa no plano recomendado da Viagem de julho.

    python -m scripts.score_breakdown
"""

import sys

from engine import run
from engine.candidates import generate_candidates
from engine.models import EngineResult
from engine.scoring import breakdown
from tests.fixtures import JULY_TRIP


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    result = run(JULY_TRIP)
    assert isinstance(result, EngineResult)
    plan = result.plans[0]
    candidate = next(
        item
        for item in generate_candidates(JULY_TRIP)
        if (item.destination.id, item.variant_label, item.start)
        == (plan.destination_id, plan.variant_label, plan.start_date)
    )
    label = plan.variant_label or "roteiro padrão"
    print(f"{candidate.destination.name}, {label}, {plan.start_date} a {plan.end_date}, score {plan.score}\n")

    for member in sorted(JULY_TRIP.members, key=lambda item: item.id):
        scores = breakdown(member, candidate, JULY_TRIP.nights)
        print(
            f"{member.id}: satisfação {scores.satisfaction:.4f} "
            f"(média {scores.base:.4f} × duração {scores.duration_factor:.2f})"
        )
        print(f"  {'termo':<12} {'origem':<10} {'peso':>5} {'valor':>6} {'peso × valor':>13}")
        for item in scores.components:
            print(
                f"  {item.kind:<12} {item.source_id:<10} {item.weight:>5.2f} "
                f"{item.match:>6.3f} {item.weight * item.match:>13.3f}"
            )
        print()


if __name__ == "__main__":
    main()
