from collections.abc import Collection, Mapping

from engine.models import Member

# Regras entre uma rodada e a seguinte: como o motivo de uma recusa entra nas
# restrições de quem recusou e quando a viagem fecha.

#: Reações ao plano recomendado que contam como acordo.
ACCEPTING = frozenset({"accepted", "accepted_with_reservation"})


def revise(previous: Member, added: Member) -> Member:
    """
    Restrições de quem recusou depois de confirmar o que o motivo da recusa
    pede. Limites se somam: o novo vale junto com os anteriores. Uma preferência
    nova substitui a anterior do mesmo tipo, porque é a opinião mais recente.
    """
    replaced = {type(item) for item in added.soft}
    return Member(
        previous.id,
        hard=(*previous.hard, *added.hard),
        soft=(*(item for item in previous.soft if type(item) not in replaced), *added.soft),
        position=previous.position,
    )


def is_agreed(respondent_ids: Collection[str], verdicts: Mapping[str, str]) -> bool:
    """
    A viagem fecha quando todos que responderam aceitaram o plano recomendado
    da rodada mais recente (aceito ou aceito com ressalva) e ninguém o recusou.
    verdicts: a reação de cada participante a esse plano.
    """
    if not respondent_ids or "rejected" in verdicts.values():
        return False
    return all(verdicts.get(member_id) in ACCEPTING for member_id in respondent_ids)
