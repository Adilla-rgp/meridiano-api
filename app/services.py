from dataclasses import asdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import convert, models, queries, schemas
from app.security import hash_token, new_token
from engine import run
from engine.models import EngineInputError

# Escritas usadas pelas rotas e pelo comando que cria a viagem de demonstração.
# Validam formato e referências; quem decide é o motor.


def create_trip(session: Session, data: schemas.CreateTripInput) -> tuple[models.Trip, str, str]:
    """Cria a viagem e quem organiza. Devolve a viagem, o admin_token e o convite de quem organiza."""
    found = set(
        session.scalars(
            select(models.CatalogDestination.id).where(models.CatalogDestination.id.in_(data.destination_ids))
        )
    )
    if missing := [i for i in data.destination_ids if i not in found]:
        raise HTTPException(422, f"Destino fora do catálogo: {', '.join(missing)}.")

    admin_token = new_token()
    trip = models.Trip(
        title=data.title,
        admin_token_hash=hash_token(admin_token),
        date_window_start=data.date_window_start,
        date_window_end=data.date_window_end,
        nights=data.nights,
        alpha=data.alpha,
        status="collecting",
    )
    session.add(trip)
    session.flush()
    session.add_all(
        models.TripDestination(trip_id=trip.id, destination_id=destination_id, position=index)
        for index, destination_id in enumerate(data.destination_ids)
    )
    [(organizer, organizer_token)] = add_members(session, trip, [data.organizer_name], is_organizer=True)
    trip.organizer_id = organizer.id
    return trip, admin_token, organizer_token


def add_members(
    session: Session, trip: models.Trip, names: list[str], is_organizer: bool = False
) -> list[tuple[models.Member, str]]:
    """Gera um convite por nome. O token só existe na resposta: o banco guarda o hash."""
    session.refresh(trip, with_for_update=True)
    current = session.scalar(select(func.count()).where(models.Member.trip_id == trip.id)) or 0
    if current + len(names) > schemas.MAX_MEMBERS:
        raise HTTPException(422, f"A viagem aceita no máximo {schemas.MAX_MEMBERS} pessoas.")

    created = []
    for offset, name in enumerate(names):
        token = new_token()
        member = models.Member(
            trip_id=trip.id,
            position=current + offset,
            display_name=name,
            invite_token_hash=hash_token(token),
            is_organizer=is_organizer,
        )
        session.add(member)
        created.append((member, token))
    session.flush()
    return created


def reissue_invite(session: Session, member: models.Member) -> str:
    """Novo link de convite; o anterior deixa de valer."""
    token = new_token()
    member.invite_token_hash = hash_token(token)
    session.flush()
    return token


def save_constraints(
    session: Session, member: models.Member, data: schemas.ConstraintsInput
) -> models.ConstraintSet:
    """Nova versão das restrições confirmadas; os resumos que faltam vêm do motor."""
    destinations = queries.trip_destinations(session, member.trip_id)
    trip_ids = {row.id for row in destinations}
    cited = {
        destination_id
        for item in [*data.hard, *data.soft]
        for destination_id in getattr(item, "destination_ids", [])
    }
    if unknown := sorted(cited - trip_ids):
        raise HTTPException(422, f"Destino que não está na viagem: {', '.join(unknown)}.")

    data = convert.with_summaries(data, destinations)
    previous = queries.latest_constraints(session, member.id)
    record = models.ConstraintSet(
        member_id=member.id,
        raw_text=data.raw_text,
        hard=convert.items_json(data.hard),
        soft=convert.items_json(data.soft),
        version=(previous.version if previous else 0) + 1,
    )
    session.add(record)
    session.flush()
    session.refresh(record)
    member.responded_at = record.confirmed_at
    return record


MIN_RESPONSES_FOR_PLANS = 2


def generate_round(session: Session, trip: models.Trip) -> int:
    """Roda o motor com a resposta mais recente de cada um e grava a rodada. Devolve o número dela."""
    session.refresh(trip, with_for_update=True)
    respondents = queries.respondents(session, trip.id)
    if len(respondents) < MIN_RESPONSES_FOR_PLANS:
        raise HTTPException(422, "São necessárias pelo menos 2 respostas para gerar planos.")

    destinations = queries.trip_destinations(session, trip.id)
    try:
        result = run(convert.trip_input(trip, destinations, [member for _, member in respondents]))
    except EngineInputError as error:
        raise HTTPException(422, str(error)) from error

    round_number = (queries.latest_round(session, trip.id) or 0) + 1
    session.add(
        models.PlanRound(
            trip_id=trip.id,
            round=round_number,
            alpha=result.alpha,
            alternatives_evaluated=result.alternatives_evaluated,
            excluded_destinations=[asdict(item) for item in result.excluded_destinations],
            blocking_limits=[asdict(item) for item in result.blocking_limits],
        )
    )
    session.flush()
    session.add_all(
        models.Plan(
            trip_id=trip.id,
            round=round_number,
            position=position,
            destination_id=plan.destination_id,
            variant_label=plan.variant_label,
            start_date=plan.start_date,
            end_date=plan.end_date,
            est_cost_per_person=plan.est_cost_per_person,
            score=plan.score,
            alpha=result.alpha,
            alternatives_evaluated=result.alternatives_evaluated,
            # O motor só devolve planos que respeitam todos os limites.
            violated_limits=0,
            per_member_scores=[asdict(item) for item in plan.per_member_scores],
            explanation=[asdict(item) for item in plan.explanation],
        )
        for position, plan in enumerate(result.plans)
    )
    trip.status = "planned" if result.plans else "collecting"
    session.flush()
    return round_number
