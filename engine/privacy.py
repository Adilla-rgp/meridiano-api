from engine.candidates import generate_candidates, limit_kind, violates
from engine.models import EngineInputError, LimitKind, LimitRef, MemberLimit, TripInput

# Orçamento é confidencial. Nas saídas para o grupo (planos, destinos excluídos,
# limites que bloqueiam), um limite de orçamento aparece só como "budget", sem
# member_id, e as justificativas não falam de orçamento. Cada pessoa vê os
# próprios limites, com o que eles eliminam, por limits_for_member().


def group_ref(member_id: str, kind: LimitKind) -> LimitRef:
    """Como o grupo vê um limite: o de orçamento não identifica ninguém."""
    return LimitRef(None if kind == "budget" else member_id, kind)


def limits_for_member(trip: TripInput, member_id: str) -> tuple[MemberLimit, ...]:
    """
    Só os limites desta pessoa, cada um com os destinos da viagem que ele
    elimina sozinho (nenhum roteiro do destino o respeita). Para a tela dela,
    nunca para o grupo.
    """
    member = next((item for item in trip.members if item.id == member_id), None)
    if member is None:
        raise EngineInputError("Participante não encontrado na viagem.")

    candidates = list(generate_candidates(trip))
    result: list[MemberLimit] = []
    for constraint in member.hard:
        eliminated = tuple(
            destination.id
            for destination in sorted(trip.destinations, key=lambda item: item.id)
            if all(violates(c, constraint) for c in candidates if c.destination.id == destination.id)
        )
        result.append(MemberLimit(constraint.id, limit_kind(constraint), eliminated))
    return tuple(result)
