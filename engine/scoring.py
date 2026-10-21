from dataclasses import dataclass
from typing import Literal

from engine.candidates import Candidate
from engine.models import Budget, Member, PreferClimate, PreferDestination, PreferPace, PreferTags

# Satisfação de cada pessoa com um candidato, de 0 a 1:
#
#   s_i = Σ w_k · m_k / Σ w_k
#
# m_k é quanto o candidato atende cada preferência declarada, mais dois termos
# implícitos: folga no orçamento (só para quem tem limite de orçamento) e dias
# de viagem. Quem não declarou nada fica com 1 no roteiro padrão.
#
# O score do plano combina as satisfações pelo critério de equilíbrio:
#
#   score(p) = (1 − α) · média(s_i(p)) + α · min(s_i(p))

CLIMATE_ORDER = {"hot": 0, "mild": 1, "cold": 2}
PACE_ORDER = {"relaxed": 0, "balanced": 1, "intense": 2}

BUDGET_SLACK_WEIGHT = 0.5
#: Folga, em fração do limite, a partir da qual o orçamento conta como plenamente atendido.
BUDGET_COMFORTABLE_SLACK = 0.2
DURATION_WEIGHT = 0.3

ComponentKind = Literal["destination", "tags", "climate", "pace", "budget", "duration"]


@dataclass(frozen=True)
class Component:
    """Um termo da satisfação; as justificativas são montadas a partir deles."""

    kind: ComponentKind
    #: Id da preferência de origem, ou o próprio kind nos termos implícitos.
    source_id: str
    weight: float
    match: float
    #: Para preferências de tags: as que o destino tem e as que faltam.
    matched_tags: tuple[str, ...] = ()
    missing_tags: tuple[str, ...] = ()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ordinal_match(distance: int) -> float:
    """Escala de três pontos: igual 1, vizinho 0,5, oposto 0."""
    return 1 - distance / 2


def components(member: Member, candidate: Candidate, trip_nights: int) -> list[Component]:
    destination = candidate.destination
    result: list[Component] = []

    for pref in member.soft:
        if pref.weight <= 0:
            continue
        match pref:
            case PreferDestination(destination_ids=ids):
                result.append(Component("destination", pref.id, pref.weight, float(destination.id in ids)))
            case PreferTags(tags=tags) if tags:
                matched = tuple(tag for tag in tags if tag in destination.tags)
                missing = tuple(tag for tag in tags if tag not in destination.tags)
                result.append(
                    Component("tags", pref.id, pref.weight, len(matched) / len(tags), matched, missing)
                )
            case PreferClimate(climates=climates) if climates:
                distance = min(abs(CLIMATE_ORDER[c] - CLIMATE_ORDER[destination.climate]) for c in climates)
                result.append(Component("climate", pref.id, pref.weight, _ordinal_match(distance)))
            case PreferPace(pace=pace):
                distance = abs(PACE_ORDER[pace] - PACE_ORDER[destination.pace])
                result.append(Component("pace", pref.id, pref.weight, _ordinal_match(distance)))

    budgets = [item.max_per_person for item in member.hard if isinstance(item, Budget)]
    if budgets:
        limit = min(budgets)
        slack = (limit - candidate.cost) / (BUDGET_COMFORTABLE_SLACK * limit)
        result.append(Component("budget", "budget", BUDGET_SLACK_WEIGHT, _clamp(slack)))

    result.append(Component("duration", "duration", DURATION_WEIGHT, candidate.nights / trip_nights))
    return result


def satisfaction(items: list[Component]) -> float:
    total_weight = sum(item.weight for item in items)
    return sum(item.weight * item.match for item in items) / total_weight


def balance_score(scores: list[float], alpha: float) -> float:
    if not 0 <= alpha <= 1:
        raise ValueError(f"α deve estar entre 0 e 1, recebido {alpha}")
    if not scores:
        return 0.0
    mean = sum(scores) / len(scores)
    return (1 - alpha) * mean + alpha * min(scores)
