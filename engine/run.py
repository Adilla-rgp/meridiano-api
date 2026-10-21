from collections import Counter

from engine.candidates import Candidate, generate_candidates, violations
from engine.explain import CLIMATE_LABEL, PACE_LABEL, explain, join_pt
from engine.models import (
    EngineInputError,
    EngineResult,
    Infeasible,
    Member,
    MemberExplanation,
    MemberScore,
    PlanResult,
    PreferClimate,
    PreferPace,
    TripInput,
)
from engine.scoring import CLIMATE_ORDER, balance_score, components, satisfaction

MAX_ALTERNATIVES = 3
#: Casas decimais dos scores devolvidos; a ordenação usa o valor arredondado.
SCORE_DIGITS = 4


def run(trip: TripInput) -> EngineResult | Infeasible:
    """
    Gera até 3 alternativas, da mais para a menos justa. Determinístico: a mesma
    entrada, em qualquer ordem de destinos ou participantes, dá o mesmo resultado.
    """
    _validate(trip)
    members = tuple(sorted(trip.members, key=lambda item: item.id))
    candidates = list(generate_candidates(trip))

    feasible: list[Candidate] = []
    blocked: list[list[tuple[str, str]]] = []
    for candidate in candidates:
        found = violations(candidate, members)
        if found:
            blocked.append(found)
        else:
            feasible.append(candidate)

    if not feasible:
        return _find_blocker(members, blocked, len(candidates))

    # A satisfação não depende do dia de ida, então cada destino e variante fica
    # com o primeiro dia viável. Assim as 3 alternativas nunca são o mesmo
    # roteiro deslocado em um dia.
    best: dict[tuple[str, str | None], Candidate] = {}
    for candidate in feasible:
        best.setdefault((candidate.destination.id, candidate.variant_label), candidate)

    plans = sorted(
        (_score(candidate, members, trip) for candidate in best.values()),
        key=lambda plan: (-plan.score, plan.variant_label is not None, plan.destination_id),
    )
    return EngineResult(
        plans=tuple(plans[:MAX_ALTERNATIVES]),
        alpha=trip.alpha,
        alternatives_evaluated=len(candidates),
    )


def _validate(trip: TripInput) -> None:
    if not 0 <= trip.alpha <= 1:
        raise EngineInputError(f"α deve estar entre 0 e 1, recebido {trip.alpha}")
    if trip.nights < 1:
        raise EngineInputError("A viagem precisa ter pelo menos 1 noite.")
    if (trip.window_end - trip.window_start).days < trip.nights:
        raise EngineInputError("A janela de datas é menor que a duração da viagem.")
    if not trip.destinations:
        raise EngineInputError("Informe pelo menos um destino.")
    if not trip.members:
        raise EngineInputError("Informe pelo menos um participante.")


def _labels(member: Member) -> dict[str, str]:
    """Rótulo de cada preferência de clima e ritmo, para as justificativas."""
    labels: dict[str, str] = {}
    for pref in member.soft:
        match pref:
            case PreferPace(pace=pace):
                labels[pref.id] = PACE_LABEL[pace]
            case PreferClimate(climates=climates) if climates:
                labels[pref.id] = join_pt([CLIMATE_LABEL[c] for c in sorted(climates, key=CLIMATE_ORDER.get)])
    return labels


def _score(candidate: Candidate, members: tuple[Member, ...], trip: TripInput) -> PlanResult:
    per_member: list[MemberScore] = []
    texts: list[MemberExplanation] = []
    for member in members:
        items = components(member, candidate, trip.nights)
        per_member.append(MemberScore(member.id, satisfaction(items)))
        texts.append(
            MemberExplanation(member.id, explain(items, _labels(member), trip.nights - candidate.nights))
        )

    score = balance_score([item.score for item in per_member], trip.alpha)
    return PlanResult(
        destination_id=candidate.destination.id,
        variant_label=candidate.variant_label,
        start_date=candidate.start,
        end_date=candidate.end,
        est_cost_per_person=candidate.cost,
        score=round(score, SCORE_DIGITS),
        per_member_scores=tuple(
            MemberScore(item.member_id, round(item.score, SCORE_DIGITS)) for item in per_member
        ),
        explanation=tuple(texts),
    )


def _find_blocker(
    members: tuple[Member, ...], blocked: list[list[tuple[str, str]]], evaluated: int
) -> Infeasible:
    """
    O limite que mais bloqueia é o que, retirado sozinho, libera mais candidatos.
    Empate: o que aparece em mais violações; depois a ordem de participante e de limite.
    """
    unlocked = Counter(found[0] for found in blocked if len(found) == 1)
    total = Counter(pair for found in blocked for pair in found)
    order = [(member.id, constraint.id) for member in members for constraint in member.hard]
    member_id, constraint_id = max(order, key=lambda pair: (unlocked[pair], total[pair], -order.index(pair)))
    return Infeasible(
        member_id=member_id,
        constraint_id=constraint_id,
        unlocked_alternatives=unlocked[(member_id, constraint_id)],
        alternatives_evaluated=evaluated,
    )
