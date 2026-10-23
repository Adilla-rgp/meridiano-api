from dataclasses import dataclass
from datetime import date
from typing import Literal

# Entradas e saídas do motor. Estruturas imutáveis e sem dependência de banco
# ou de Pydantic: a API converte os modelos dela para estes antes de chamar
# engine.run(). Os nomes de campo seguem o contrato (docs/especificacao.md).

Climate = Literal["hot", "mild", "cold"]
Pace = Literal["relaxed", "balanced", "intense"]


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    climate: Climate
    pace: Pace
    tags: tuple[str, ...]
    #: Passagem de ida e volta por pessoa.
    fixed_cost: float
    #: Hospedagem e gastos por noite, por pessoa.
    nightly_cost: float

    def cost_for(self, nights: int) -> float:
        return self.fixed_cost + nights * self.nightly_cost


# Limites: nunca são violados pelo motor.


@dataclass(frozen=True)
class DateRange:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class Budget:
    id: str
    max_per_person: float
    all_inclusive: bool


@dataclass(frozen=True)
class ExcludeClimate:
    id: str
    climates: frozenset[Climate]


@dataclass(frozen=True)
class ExcludeDestination:
    id: str
    destination_ids: frozenset[str]


HardConstraint = DateRange | Budget | ExcludeClimate | ExcludeDestination


# Preferências: entram na satisfação com um peso de 0 a 1.


@dataclass(frozen=True)
class PreferPace:
    id: str
    pace: Pace
    weight: float


@dataclass(frozen=True)
class PreferClimate:
    id: str
    climates: frozenset[Climate]
    weight: float


@dataclass(frozen=True)
class PreferDestination:
    id: str
    #: Em ordem de preferência: o primeiro é o escolhido.
    destination_ids: tuple[str, ...]
    weight: float


@dataclass(frozen=True)
class PreferTags:
    id: str
    tags: tuple[str, ...]
    weight: float


SoftConstraint = PreferPace | PreferClimate | PreferDestination | PreferTags


@dataclass(frozen=True)
class Member:
    """Participante que já respondeu, com a versão mais recente das restrições."""

    id: str
    hard: tuple[HardConstraint, ...] = ()
    soft: tuple[SoftConstraint, ...] = ()
    #: Ordem do convite (0 é quem organiza). Só desempata listas; nunca muda um score.
    position: int = 0


@dataclass(frozen=True)
class TripInput:
    window_start: date
    window_end: date
    #: Duração do roteiro padrão, definida pelo organizador.
    nights: int
    alpha: float
    destinations: tuple[Destination, ...]
    members: tuple[Member, ...]


# Saídas


@dataclass(frozen=True)
class MemberScore:
    member_id: str
    score: float
    #: Falso para quem não declarou nenhuma preferência: fica fora do score do plano.
    has_preferences: bool
    #: Maior satisfação que a pessoa teria em qualquer candidato que respeita os limites do grupo.
    best_possible: float


@dataclass(frozen=True)
class MemberExplanation:
    member_id: str
    text: str


@dataclass(frozen=True)
class PlanResult:
    destination_id: str
    variant_label: str | None
    start_date: date
    end_date: date
    est_cost_per_person: float
    score: float
    per_member_scores: tuple[MemberScore, ...]
    explanation: tuple[MemberExplanation, ...]


LimitKind = Literal["date_range", "budget", "exclude_climate", "exclude_destination"]


@dataclass(frozen=True)
class LimitRef:
    """
    Qual limite, de quem, como o grupo vê. Só o tipo, nunca o valor. Limite de
    orçamento não identifica ninguém: member_id é nulo.
    """

    member_id: str | None
    kind: LimitKind


@dataclass(frozen=True)
class MemberLimit:
    """Um limite da própria pessoa e os destinos da viagem que ele elimina sozinho, para a tela dela."""

    constraint_id: str
    kind: LimitKind
    eliminated_destination_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExcludedDestination:
    destination_id: str
    #: "limit": nenhum candidato do destino respeita os limites; "lower_score": viável, com score menor.
    reason: Literal["limit", "lower_score"]
    #: Limites que eliminam o destino; vazio quando o motivo é score menor.
    limits: tuple[LimitRef, ...]
    #: Melhor score do destino entre as variantes; nulo quando o motivo é limite.
    best_score: float | None


@dataclass(frozen=True)
class BlockingLimit:
    """Limite que elimina candidatos da rodada, como o grupo vê: orçamento sem member_id."""

    member_id: str | None
    kind: LimitKind
    #: Quantos candidatos (destino × variante × dia de ida) este limite elimina.
    eliminated_candidates: int


@dataclass(frozen=True)
class EngineResult:
    #: Do maior para o menor score; o primeiro é o recomendado. Vazio quando nada é viável.
    plans: tuple[PlanResult, ...]
    alpha: float
    alternatives_evaluated: int
    #: Destinos da viagem que não aparecem em nenhum plano devolvido, na ordem do id.
    excluded_destinations: tuple[ExcludedDestination, ...]
    #: Só quando nada é viável: os limites que eliminam candidatos, do que mais elimina para o que menos.
    blocking_limits: tuple[BlockingLimit, ...] = ()


class EngineInputError(ValueError):
    """Entrada que o motor não aceita (α fora de 0 a 1, janela menor que a viagem etc.)."""
