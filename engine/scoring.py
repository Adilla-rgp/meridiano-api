from dataclasses import dataclass
from typing import Literal

from engine.candidates import Candidate
from engine.models import Budget, Member, PreferClimate, PreferDestination, PreferPace, PreferTags

# Satisfação de cada pessoa com um candidato, de 0 a 1:
#
#   s_i = (Σ w_k · m_k / Σ w_k) · fator de duração
#
# m_k é quanto o candidato atende cada preferência que a pessoa declarou. O que
# ela não mencionou é neutro (0,5) e por isso fica fora da média: não puxa para
# cima nem para baixo. Quem não declarou nada fica em 0,5.
#
# Termos implícitos:
# - folga no orçamento, só para quem tem limite de orçamento. Vai de 0,5 (cabe,
#   mas no limite) a 1 (folga confortável): respeitar o limite nunca fica
#   abaixo do neutro.
# - duração: no roteiro padrão não entra. No roteiro curto multiplica a
#   satisfação de todos, porque a duração foi escolhida para o grupo. É fator,
#   não termo da média, para que perder dias nunca aumente a satisfação de
#   quem estava abaixo do valor do termo.
#
# O score do plano combina as satisfações pelo critério de equilíbrio:
#
#   score(p) = (1 − α) · média(s_i(p)) + α · min(s_i(p))

NEUTRAL = 0.5

DESTINATION_FIRST = 1.0
#: Destino que a pessoa listou, mas não em primeiro.
DESTINATION_LISTED = 0.75
#: Destino que a pessoa não listou. Destino vetado é limite e nem chega aqui.
DESTINATION_UNLISTED = 0.4

CLIMATE_ORDER = {"hot": 0, "mild": 1, "cold": 2}
PACE_VALUE = {"relaxed": 0.0, "balanced": 0.5, "intense": 1.0}

BUDGET_WEIGHT = 0.5
#: Folga, em fração do limite, a partir da qual o orçamento conta como plenamente atendido.
BUDGET_COMFORTABLE_SLACK = 0.2
#: Quanto da satisfação se perde quando o roteiro perde todas as noites; proporcional às noites perdidas.
DURATION_PENALTY = 0.3

ComponentKind = Literal["destination", "tags", "climate", "pace", "budget"]


@dataclass(frozen=True)
class Component:
    """Um termo da média; as justificativas são montadas a partir deles."""

    kind: ComponentKind
    #: Id da preferência de origem, ou "budget" no termo implícito.
    source_id: str
    weight: float
    match: float
    #: Para preferências de tags: as que o destino tem e as que faltam.
    matched_tags: tuple[str, ...] = ()
    missing_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Breakdown:
    components: tuple[Component, ...]
    #: 1 no roteiro padrão; abaixo de 1 no roteiro curto.
    duration_factor: float

    @property
    def base(self) -> float:
        total_weight = sum(item.weight for item in self.components)
        if total_weight == 0:
            return NEUTRAL
        return sum(item.weight * item.match for item in self.components) / total_weight

    @property
    def satisfaction(self) -> float:
        return self.base * self.duration_factor


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def destination_match(destination_id: str, preferred: tuple[str, ...]) -> float:
    if preferred and destination_id == preferred[0]:
        return DESTINATION_FIRST
    if destination_id in preferred:
        return DESTINATION_LISTED
    return DESTINATION_UNLISTED


def climate_match(destination_climate: str, preferred: frozenset[str]) -> float:
    """Quente, ameno, frio: igual 1, vizinho 0,5, oposto 0."""
    distance = min(abs(CLIMATE_ORDER[c] - CLIMATE_ORDER[destination_climate]) for c in preferred)
    return 1 - distance / 2


def pace_match(destination_pace: str, preferred: str) -> float:
    return 1 - abs(PACE_VALUE[preferred] - PACE_VALUE[destination_pace])


def budget_match(cost: float, limit: float) -> float:
    slack = (limit - cost) / (BUDGET_COMFORTABLE_SLACK * limit)
    return NEUTRAL + (1 - NEUTRAL) * _clamp(slack)


def duration_factor(nights: int, trip_nights: int) -> float:
    lost = max(0, trip_nights - nights) / trip_nights
    return 1 - DURATION_PENALTY * lost


def breakdown(member: Member, candidate: Candidate, trip_nights: int) -> Breakdown:
    destination = candidate.destination
    items: list[Component] = []

    for pref in member.soft:
        if pref.weight <= 0:
            continue
        match pref:
            case PreferDestination(destination_ids=ids) if ids:
                items.append(
                    Component("destination", pref.id, pref.weight, destination_match(destination.id, ids))
                )
            case PreferTags(tags=tags) if tags:
                matched = tuple(tag for tag in tags if tag in destination.tags)
                missing = tuple(tag for tag in tags if tag not in destination.tags)
                items.append(
                    Component("tags", pref.id, pref.weight, len(matched) / len(tags), matched, missing)
                )
            case PreferClimate(climates=climates) if climates:
                items.append(
                    Component("climate", pref.id, pref.weight, climate_match(destination.climate, climates))
                )
            case PreferPace(pace=pace):
                items.append(Component("pace", pref.id, pref.weight, pace_match(destination.pace, pace)))

    budgets = [item.max_per_person for item in member.hard if isinstance(item, Budget)]
    if budgets:
        items.append(Component("budget", "budget", BUDGET_WEIGHT, budget_match(candidate.cost, min(budgets))))

    return Breakdown(tuple(items), duration_factor(candidate.nights, trip_nights))


def balance_score(scores: list[float], alpha: float) -> float:
    if not 0 <= alpha <= 1:
        raise ValueError(f"α deve estar entre 0 e 1, recebido {alpha}")
    if not scores:
        return 0.0
    mean = sum(scores) / len(scores)
    return (1 - alpha) * mean + alpha * min(scores)
