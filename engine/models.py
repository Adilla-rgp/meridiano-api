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


@dataclass(frozen=True)
class EngineResult:
    #: Do maior para o menor score; o primeiro é o recomendado.
    plans: tuple[PlanResult, ...]
    alpha: float
    alternatives_evaluated: int


@dataclass(frozen=True)
class Infeasible:
    """Nenhum candidato respeita todos os limites: aponta o que mais bloqueia."""

    member_id: str
    constraint_id: str
    #: Quantos candidatos passariam se só este limite fosse retirado.
    unlocked_alternatives: int
    alternatives_evaluated: int


class EngineInputError(ValueError):
    """Entrada que o motor não aceita (α fora de 0 a 1, janela menor que a viagem etc.)."""
