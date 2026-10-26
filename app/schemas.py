from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Modelos da API, no formato do contrato do front (planner-vite/src/types/api.ts):
# mesmos nomes de campo, em snake_case. Só validação de formato; as regras ficam
# no motor (engine/).

Climate = Literal["hot", "mild", "cold"]
Pace = Literal["relaxed", "balanced", "intense"]
TripStatus = Literal["collecting", "planned", "agreed"]
Verdict = Literal["accepted", "accepted_with_reservation", "rejected"]
LimitKind = Literal["date_range", "budget", "exclude_climate", "exclude_destination", "exclude_tags"]
TensionCriterion = Literal["climate", "dates", "pace"]

ItemId = Annotated[str, Field(min_length=1, max_length=64)]
Weight = Annotated[float, Field(ge=0, le=1)]
DestinationIds = Annotated[list[str], Field(min_length=1, max_length=4)]
Climates = Annotated[list[Climate], Field(min_length=1, max_length=3)]
Tags = Annotated[list[Annotated[str, Field(min_length=1, max_length=40)]], Field(min_length=1, max_length=10)]

MAX_MEMBERS = 8
MIN_DESTINATIONS = 2
MAX_DESTINATIONS = 4
MAX_RAW_TEXT = 2000


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# Catálogo


class Destination(Schema):
    id: str
    name: str
    state: str
    climate: Climate
    pace: Pace
    fixed_cost: float
    nightly_cost: float
    #: fixed_cost + noites × nightly_cost, com as noites da viagem (6 no catálogo).
    est_cost_per_person: float
    cost_source: str
    tags: list[str]


# Viagem e participantes


class Trip(Schema):
    id: str
    title: str
    organizer_id: str | None
    date_window_start: date
    date_window_end: date
    nights: int
    alpha: float
    status: TripStatus
    created_at: datetime


class Member(Schema):
    id: str
    trip_id: str
    display_name: str
    #: Só na resposta que cria o convite (ou gera um novo): o banco guarda apenas o hash.
    invite_token: str | None = None
    is_organizer: bool
    responded_at: datetime | None


class GroupMember(Schema):
    """Participante como os outros convidados o veem: sem o token do convite."""

    id: str
    display_name: str
    is_organizer: bool
    responded_at: datetime | None


class TripDetail(Trip):
    destinations: list[Destination]
    members: list[Member]
    latest_round: int | None


class TripCreated(TripDetail):
    """Resposta de POST /trips. Os tokens só aparecem aqui."""

    #: Vai no cabeçalho X-Admin-Token das rotas do organizador.
    admin_token: str
    #: Link de administração para o organizador guardar; o token vai no fragmento, que não chega a servidores.
    admin_url: str


class CreateTripInput(Input):
    title: str = Field(min_length=1, max_length=120)
    #: Nome de quem organiza; vira o primeiro participante, com is_organizer.
    organizer_name: str = Field(min_length=1, max_length=60)
    destination_ids: list[str] = Field(min_length=MIN_DESTINATIONS, max_length=MAX_DESTINATIONS)
    date_window_start: date
    date_window_end: date
    nights: int = Field(default=6, ge=1, le=30)
    alpha: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _check(self) -> "CreateTripInput":
        if len(set(self.destination_ids)) != len(self.destination_ids):
            raise ValueError("Os destinos não podem se repetir.")
        if (self.date_window_end - self.date_window_start).days < self.nights:
            raise ValueError("A janela de datas é menor que a duração da viagem.")
        return self


class CreateMembersInput(Input):
    display_names: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )


# Restrições


class Item(Input):
    id: ItemId
    #: Frase pronta para exibição. Na entrada, o que a pessoa confirmou; a API gera quando falta.
    summary: str = Field(default="", max_length=200)


class DateRangeItem(Item):
    kind: Literal["date_range"]
    start: date
    end: date

    @model_validator(mode="after")
    def _check(self) -> "DateRangeItem":
        if self.end < self.start:
            raise ValueError("A data final vem antes da inicial.")
        return self


class BudgetItem(Item):
    kind: Literal["budget"]
    max_per_person: float = Field(gt=0, le=1_000_000)
    all_inclusive: bool


class ExcludeClimateItem(Item):
    kind: Literal["exclude_climate"]
    climates: Climates


class ExcludeDestinationItem(Item):
    kind: Literal["exclude_destination"]
    destination_ids: DestinationIds


class ExcludeTagsItem(Item):
    kind: Literal["exclude_tags"]
    tags: Tags


class PaceItem(Item):
    kind: Literal["pace"]
    pace: Pace
    weight: Weight


class PreferClimateItem(Item):
    kind: Literal["prefer_climate"]
    climates: Climates
    weight: Weight


class PreferDestinationItem(Item):
    kind: Literal["prefer_destination"]
    #: Em ordem de preferência.
    destination_ids: DestinationIds
    weight: Weight


class PreferTagsItem(Item):
    kind: Literal["prefer_tags"]
    tags: Tags
    weight: Weight


HardConstraint = Annotated[
    DateRangeItem | BudgetItem | ExcludeClimateItem | ExcludeDestinationItem | ExcludeTagsItem,
    Field(discriminator="kind"),
]
SoftConstraint = Annotated[
    PaceItem | PreferClimateItem | PreferDestinationItem | PreferTagsItem, Field(discriminator="kind")
]


class ConstraintsInput(Input):
    """Corpo de PUT /invite/{token}/constraints."""

    raw_text: str = Field(max_length=MAX_RAW_TEXT)
    hard: list[HardConstraint] = Field(max_length=20)
    soft: list[SoftConstraint] = Field(max_length=20)

    @model_validator(mode="after")
    def _check(self) -> "ConstraintsInput":
        ids = [item.id for item in [*self.hard, *self.soft]]
        if len(set(ids)) != len(ids):
            raise ValueError("Cada restrição precisa de um id diferente.")
        return self


class ParseInput(Input):
    raw_text: str = Field(max_length=MAX_RAW_TEXT)


class MemberLimit(Schema):
    """Um limite da própria pessoa e os destinos que ele elimina sozinho. Só para ela."""

    constraint_id: str
    kind: LimitKind
    eliminated_destination_ids: list[str]


class ParsedConstraints(ConstraintsInput):
    member_limits: list[MemberLimit]


class Constraints(Schema):
    id: str
    member_id: str
    raw_text: str
    hard: list[HardConstraint]
    soft: list[SoftConstraint]
    confirmed_at: datetime
    version: int


class Invite(Schema):
    """GET /invite/{token}"""

    trip: Trip
    member: Member
    organizer_name: str
    member_count: int
    members: list[GroupMember]
    destinations: list[Destination]
    constraints: Constraints | None
    member_limits: list[MemberLimit]
    latest_round: int | None


# Tensões


class MemberPair(Schema):
    member_a_id: str
    member_b_id: str
    status: Literal["compatible", "conflict"]
    criterion: TensionCriterion | None


class KeyConstraint(Schema):
    id: str
    summary: str


class DestinationViability(Schema):
    destination_id: str
    accepted_count: int
    responded_count: int


class TripTensions(Schema):
    trip_id: str
    member_count: int
    responded_count: int
    most_restrictive_member_id: str | None
    pairs: list[MemberPair]
    key_constraints: list[KeyConstraint]
    viability: list[DestinationViability]


# Planos


class MemberScore(Schema):
    member_id: str
    score: float
    has_preferences: bool
    best_possible: float


class MemberExplanation(Schema):
    member_id: str
    text: str


class Plan(Schema):
    id: str
    trip_id: str
    round: int
    destination_id: str
    variant_label: str | None
    start_date: date
    end_date: date
    est_cost_per_person: float
    score: float
    alpha: float
    alternatives_evaluated: int
    violated_limits: int
    per_member_scores: list[MemberScore]
    explanation: list[MemberExplanation]


class LimitRef(Schema):
    member_id: str | None
    kind: LimitKind


class ExcludedDestination(Schema):
    destination_id: str
    reason: Literal["limit", "lower_score"]
    limits: list[LimitRef]
    best_score: float | None


class BlockingLimit(LimitRef):
    eliminated_candidates: int


class PlanRoundRecord(Schema):
    trip_id: str
    round: int
    alpha: float
    alternatives_evaluated: int
    excluded_destinations: list[ExcludedDestination]
    blocking_limits: list[BlockingLimit]
    created_at: datetime


class Reaction(Schema):
    id: str
    plan_id: str
    member_id: str
    verdict: Verdict
    comment: str | None
    reacted_at: datetime


class PlanRound(PlanRoundRecord):
    plans: list[Plan]
    recommended_plan_id: str | None
    #: O organizador recebe todas; o convidado, só as próprias.
    reactions: list[Reaction]


class CreateReactionInput(Input):
    invite_token: str = Field(min_length=1, max_length=200)
    verdict: Verdict
    comment: str | None = Field(default=None, max_length=1000)


class ConstraintDraft(Schema):
    """
    O que o motivo da recusa pede, interpretado e ainda não salvo. Só para quem
    recusou: confirma (com ou sem mudanças) em POST /plans/{id}/reactions/constraints.
    """

    hard: list[HardConstraint]
    soft: list[SoftConstraint]
    member_limits: list[MemberLimit]


class ReactionResult(Reaction):
    """Resposta de POST /plans/{id}/reactions."""

    #: Só na recusa. Listas vazias quando o motivo não traz nenhum limite ou preferência reconhecível.
    constraint_draft: ConstraintDraft | None = None
    #: Status da viagem depois da reação: "agreed" quando esta reação fechou a viagem.
    trip_status: TripStatus


class ConfirmRejectionInput(Input):
    """Corpo de POST /plans/{id}/reactions/constraints: o rascunho que a pessoa confirmou."""

    invite_token: str = Field(min_length=1, max_length=200)
    hard: list[HardConstraint] = Field(max_length=20)
    soft: list[SoftConstraint] = Field(max_length=20)

    @model_validator(mode="after")
    def _check(self) -> "ConfirmRejectionInput":
        ids = [item.id for item in [*self.hard, *self.soft]]
        if len(set(ids)) != len(ids):
            raise ValueError("Cada restrição precisa de um id diferente.")
        if not ids:
            raise ValueError("Confirme pelo menos um limite ou uma preferência.")
        return self
