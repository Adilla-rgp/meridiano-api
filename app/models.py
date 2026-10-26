import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Tabelas da especificação (meridiano/docs/especificacao.md, "Modelo de
# dados"), mais o que a implementação precisou:
# - trips.admin_token_hash e members.invite_token_hash: os tokens nunca são
#   guardados, só o hash (app/security.py);
# - position em trip_destinations, members e plans: a ordem de escolha, de
#   convite e a do motor, que não dependem de relógio;
# - catalog_destinations.pace_note: por que o destino tem aquele ritmo.


def new_id() -> str:
    return str(uuid.uuid4())


CLIMATES = ("hot", "mild", "cold")
PACES = ("relaxed", "balanced", "intense")
TRIP_STATUSES = ("collecting", "planned", "agreed")
VERDICTS = ("accepted", "accepted_with_reservation", "rejected")


def _enum(name: str, values: tuple[str, ...]) -> Enum:
    """Texto com CHECK, sem tipo enum do Postgres: incluir um valor não exige migração de tipo."""
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


class Base(DeclarativeBase):
    pass


class CatalogDestination(Base):
    __tablename__ = "catalog_destinations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(2))
    climate: Mapped[str] = mapped_column(_enum("climate", CLIMATES))
    pace: Mapped[str] = mapped_column(_enum("pace", PACES))
    pace_note: Mapped[str] = mapped_column(Text)
    #: Passagem de ida e volta, por pessoa.
    fixed_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    #: Hospedagem e gastos por noite, por pessoa.
    nightly_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    cost_source: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text))


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("date_window_end > date_window_start", name="window_order"),
        CheckConstraint("nights >= 1", name="nights_positive"),
        CheckConstraint("alpha >= 0 AND alpha <= 1", name="alpha_range"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(120))
    #: Sem conta de organizador no MVP: o id do participante que organiza.
    organizer_id: Mapped[str | None] = mapped_column(String(36))
    admin_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    date_window_start: Mapped[date] = mapped_column(Date)
    date_window_end: Mapped[date] = mapped_column(Date)
    nights: Mapped[int] = mapped_column(Integer)
    alpha: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(_enum("trip_status", TRIP_STATUSES), default="collecting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripDestination(Base):
    __tablename__ = "trip_destinations"

    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    destination_id: Mapped[str] = mapped_column(ForeignKey("catalog_destinations.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("trip_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(60))
    invite_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    is_organizer: Mapped[bool] = mapped_column(Boolean, default=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConstraintSet(Base):
    """Uma versão das restrições confirmadas por um participante; vale a de maior version."""

    __tablename__ = "constraints"
    __table_args__ = (UniqueConstraint("member_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    hard: Mapped[list[dict]] = mapped_column(JSONB)
    soft: Mapped[list[dict]] = mapped_column(JSONB)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer)


class PlanRound(Base):
    """O que é da rodada e não de um plano. Existe mesmo quando nada é viável."""

    __tablename__ = "plan_rounds"

    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    round: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha: Mapped[float] = mapped_column(Float)
    alternatives_evaluated: Mapped[int] = mapped_column(Integer)
    excluded_destinations: Mapped[list[dict]] = mapped_column(JSONB)
    blocking_limits: Mapped[list[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["trip_id", "round"], ["plan_rounds.trip_id", "plan_rounds.round"], ondelete="CASCADE"
        ),
        UniqueConstraint("trip_id", "round", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36))
    round: Mapped[int] = mapped_column(Integer)
    #: Ordem do motor: 0 é o recomendado.
    position: Mapped[int] = mapped_column(Integer)
    destination_id: Mapped[str] = mapped_column(ForeignKey("catalog_destinations.id"))
    variant_label: Mapped[str | None] = mapped_column(String(60))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    est_cost_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    score: Mapped[float] = mapped_column(Float)
    alpha: Mapped[float] = mapped_column(Float)
    alternatives_evaluated: Mapped[int] = mapped_column(Integer)
    violated_limits: Mapped[int] = mapped_column(Integer)
    per_member_scores: Mapped[list[dict]] = mapped_column(JSONB)
    explanation: Mapped[list[dict]] = mapped_column(JSONB)


class Reaction(Base):
    __tablename__ = "reactions"
    __table_args__ = (UniqueConstraint("plan_id", "member_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(_enum("verdict", VERDICTS))
    comment: Mapped[str | None] = mapped_column(Text)
    reacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
