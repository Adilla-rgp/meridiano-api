from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import convert, models, schemas
from engine import models as engine
from engine.privacy import limits_for_member

# Leituras usadas por mais de uma rota.


def trip_destinations(session: Session, trip_id: str) -> list[models.CatalogDestination]:
    """Os destinos da viagem, na ordem em que o organizador escolheu."""
    return list(
        session.scalars(
            select(models.CatalogDestination)
            .join(
                models.TripDestination, models.TripDestination.destination_id == models.CatalogDestination.id
            )
            .where(models.TripDestination.trip_id == trip_id)
            .order_by(models.TripDestination.position)
        )
    )


def trip_members(session: Session, trip_id: str) -> list[models.Member]:
    """Na ordem do convite: quem organiza primeiro."""
    return list(
        session.scalars(
            select(models.Member).where(models.Member.trip_id == trip_id).order_by(models.Member.position)
        )
    )


def latest_constraints(session: Session, member_id: str) -> models.ConstraintSet | None:
    return session.scalars(
        select(models.ConstraintSet)
        .where(models.ConstraintSet.member_id == member_id)
        .order_by(models.ConstraintSet.version.desc())
        .limit(1)
    ).first()


def latest_round(session: Session, trip_id: str) -> int | None:
    return session.scalar(select(func.max(models.PlanRound.round)).where(models.PlanRound.trip_id == trip_id))


def member_schema(member: models.Member, invite_token: str | None = None) -> schemas.Member:
    return schemas.Member(
        id=member.id,
        trip_id=member.trip_id,
        display_name=member.display_name,
        invite_token=invite_token,
        is_organizer=member.is_organizer,
        responded_at=member.responded_at,
    )


def trip_detail(
    session: Session, trip: models.Trip, constraint_parser: str, tokens: dict[str, str] | None = None
) -> schemas.TripDetail:
    """
    constraint_parser: o da configuração. tokens: os convites recém-criados, por id
    de participante, para devolver uma única vez.
    """
    tokens = tokens or {}
    return schemas.TripDetail(
        **schemas.Trip.model_validate(trip).model_dump(),
        destinations=[
            convert.destination_schema(row, trip.nights) for row in trip_destinations(session, trip.id)
        ],
        members=[member_schema(member, tokens.get(member.id)) for member in trip_members(session, trip.id)],
        latest_round=latest_round(session, trip.id),
        constraint_parser=constraint_parser,
    )


def respondents(session: Session, trip_id: str) -> list[tuple[models.Member, engine.Member]]:
    """Quem já respondeu, com a versão mais recente das restrições, já no formato do motor."""
    result = []
    for member in trip_members(session, trip_id):
        record = latest_constraints(session, member.id)
        if member.responded_at and record:
            engine_member = convert.engine_member(member.id, record.hard, record.soft, member.position)
            result.append((member, engine_member))
    return result


def plan_round(
    session: Session, trip_id: str, round_number: int, viewer_member_id: str | None
) -> schemas.PlanRound | None:
    """
    A rodada com planos e reações. viewer_member_id nulo é o organizador, que
    vê todas as reações; um convidado vê só as próprias.
    """
    record = session.get(models.PlanRound, (trip_id, round_number))
    if record is None:
        return None
    plans = list(
        session.scalars(
            select(models.Plan)
            .where(models.Plan.trip_id == trip_id, models.Plan.round == round_number)
            .order_by(models.Plan.position)
        )
    )
    reactions_query = select(models.Reaction).where(models.Reaction.plan_id.in_([plan.id for plan in plans]))
    if viewer_member_id is not None:
        reactions_query = reactions_query.where(models.Reaction.member_id == viewer_member_id)
    reactions = session.scalars(reactions_query.order_by(models.Reaction.reacted_at))
    return schemas.PlanRound(
        **schemas.PlanRoundRecord.model_validate(record).model_dump(),
        plans=[schemas.Plan.model_validate(plan) for plan in plans],
        recommended_plan_id=plans[0].id if plans else None,
        reactions=[schemas.Reaction.model_validate(reaction) for reaction in reactions],
    )


def own_limits(
    session: Session, trip: models.Trip, member_id: str, hard: list[dict]
) -> list[schemas.MemberLimit]:
    """O que cada limite desta pessoa elimina sozinho. Só para ela (engine/privacy.py)."""
    destinations = trip_destinations(session, trip.id)
    member = convert.engine_member(member_id, hard, [])
    return [
        convert.member_limit(item)
        for item in limits_for_member(convert.trip_input(trip, destinations, [member]), member_id)
    ]


def reactions_by_member(session: Session, plan_id: str) -> dict[str, models.Reaction]:
    rows = session.scalars(select(models.Reaction).where(models.Reaction.plan_id == plan_id))
    return {row.member_id: row for row in rows}
