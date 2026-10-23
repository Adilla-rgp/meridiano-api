from collections import Counter

from engine.candidates import Candidate, generate_candidates, limit_kind, violations
from engine.explain import explain
from engine.models import (
    BlockingLimit,
    EngineInputError,
    EngineResult,
    ExcludedDestination,
    LimitKind,
    LimitRef,
    Member,
    MemberExplanation,
    MemberScore,
    PlanResult,
    TripInput,
)
from engine.privacy import group_ref
from engine.scoring import Breakdown, balance_score, breakdown

MAX_ALTERNATIVES = 3
#: Casas decimais dos scores devolvidos; a ordenação usa o valor arredondado.
SCORE_DIGITS = 4

#: Limite identificado por (member_id, constraint_id), como devolve violations().
LimitKey = tuple[str, str]


def run(trip: TripInput) -> EngineResult:
    """
    Gera até 3 alternativas, da mais para a menos justa. Se nada respeita todos
    os limites, devolve plans vazio e blocking_limits. Determinístico: a mesma
    entrada, em qualquer ordem de destinos ou participantes, dá o mesmo resultado.
    """
    _validate(trip)
    members = tuple(sorted(trip.members, key=lambda item: item.id))
    candidates = list(generate_candidates(trip))
    checked = [(candidate, violations(candidate, members)) for candidate in candidates]

    if all(found for _, found in checked):
        return EngineResult(
            plans=(),
            alpha=trip.alpha,
            alternatives_evaluated=len(candidates),
            excluded_destinations=_excluded(trip, members, checked, [], []),
            blocking_limits=_blocking_limits(members, checked),
        )

    # A satisfação não depende do dia de ida, então cada destino e variante fica
    # com o primeiro dia viável. Assim as 3 alternativas nunca são o mesmo
    # roteiro deslocado em um dia.
    best: dict[tuple[str, str | None], Candidate] = {}
    for candidate, found in checked:
        if not found:
            best.setdefault((candidate.destination.id, candidate.variant_label), candidate)

    scores = {
        candidate: {m.id: breakdown(m, candidate, trip.nights) for m in members}
        for candidate in best.values()
    }
    best_possible = {
        m.id: max(by_member[m.id].satisfaction for by_member in scores.values()) for m in members
    }

    # Empate de score: roteiro padrão antes do curto, depois o menor custo. Quando
    # ninguém declarou preferências, todo score é 0 e vale só esse desempate.
    plans = sorted(
        (_plan(candidate, members, trip, scores[candidate], best_possible) for candidate in best.values()),
        key=lambda plan: (
            -plan.score,
            plan.variant_label is not None,
            plan.est_cost_per_person,
            plan.destination_id,
        ),
    )
    returned = plans[:MAX_ALTERNATIVES]
    return EngineResult(
        plans=tuple(returned),
        alpha=trip.alpha,
        alternatives_evaluated=len(candidates),
        excluded_destinations=_excluded(trip, members, checked, plans, returned),
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


def _plan(
    candidate: Candidate,
    members: tuple[Member, ...],
    trip: TripInput,
    scores: dict[str, Breakdown],
    best_possible: dict[str, float],
) -> PlanResult:
    """Só quem declarou preferências entra no score (média e mínimo)."""
    nights_lost = trip.nights - candidate.nights
    counted = [scores[m.id].satisfaction for m in members if scores[m.id].has_preferences]
    return PlanResult(
        destination_id=candidate.destination.id,
        variant_label=candidate.variant_label,
        start_date=candidate.start,
        end_date=candidate.end,
        est_cost_per_person=candidate.cost,
        score=round(balance_score(counted, trip.alpha), SCORE_DIGITS),
        per_member_scores=tuple(
            MemberScore(
                member_id=m.id,
                score=round(scores[m.id].satisfaction, SCORE_DIGITS),
                has_preferences=scores[m.id].has_preferences,
                best_possible=round(best_possible[m.id], SCORE_DIGITS),
            )
            for m in members
        ),
        explanation=tuple(
            MemberExplanation(m.id, explain(m, scores[m.id], nights_lost, candidate.destination.climate))
            for m in members
        ),
    )


def _excluded(
    trip: TripInput,
    members: tuple[Member, ...],
    checked: list[tuple[Candidate, list[LimitKey]]],
    plans: list[PlanResult],
    returned: list[PlanResult],
) -> tuple[ExcludedDestination, ...]:
    """Por que cada destino da viagem ficou fora das alternativas devolvidas."""
    returned_ids = {plan.destination_id for plan in returned}
    kinds: dict[LimitKey, LimitKind] = {(m.id, c.id): limit_kind(c) for m in members for c in m.hard}
    result: list[ExcludedDestination] = []

    for destination in sorted(trip.destinations, key=lambda item: item.id):
        if destination.id in returned_ids:
            continue
        own = [plan.score for plan in plans if plan.destination_id == destination.id]
        if own:
            result.append(ExcludedDestination(destination.id, "lower_score", (), max(own)))
            continue
        found = [limits for candidate, limits in checked if candidate.destination.id == destination.id]
        result.append(ExcludedDestination(destination.id, "limit", _excluding_limits(found, kinds), None))

    return tuple(result)


def _excluding_limits(found: list[list[LimitKey]], kinds: dict[LimitKey, LimitKind]) -> tuple[LimitRef, ...]:
    """
    Os limites que ferem todos os candidatos do destino. Se nenhum fere todos
    (o destino cai por combinação de limites), os que, retirados sozinhos,
    liberariam algum candidato; senão, todos os envolvidos.
    """
    blocking = set.intersection(*(set(limits) for limits in found))
    if not blocking:
        blocking = {limits[0] for limits in found if len(limits) == 1}
    if not blocking:
        blocking = {key for limits in found for key in limits}

    refs: list[LimitRef] = []
    for key in kinds:  # ordem de participante e de limite
        ref = group_ref(key[0], kinds[key])
        if key in blocking and ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _blocking_limits(
    members: tuple[Member, ...], checked: list[tuple[Candidate, list[LimitKey]]]
) -> tuple[BlockingLimit, ...]:
    """
    Cada limite que elimina algum candidato, com quantos elimina. Os de
    orçamento viram um só, sem member_id, e um candidato conta uma vez mesmo
    que vários orçamentos o eliminem. Empate: ordem do convite e do limite.
    """
    by_invite = sorted(members, key=lambda item: (item.position, item.id))
    kinds: dict[LimitKey, LimitKind] = {(m.id, c.id): limit_kind(c) for m in by_invite for c in m.hard}
    order: list[LimitRef] = []
    for (member_id, _), kind in kinds.items():
        ref = group_ref(member_id, kind)
        if ref not in order:
            order.append(ref)

    counts: Counter[LimitRef] = Counter()
    for _, found in checked:
        counts.update({group_ref(member_id, kinds[(member_id, cid)]) for member_id, cid in found})

    ranked = sorted((ref for ref in order if counts[ref]), key=lambda ref: (-counts[ref], order.index(ref)))
    return tuple(BlockingLimit(ref.member_id, ref.kind, counts[ref]) for ref in ranked)
