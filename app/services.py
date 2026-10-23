from dataclasses import asdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import convert, models, queries, schemas
from app.parsing import ConstraintParser
from app.security import hash_token, new_token
from engine import run
from engine.models import EngineInputError
from engine.rounds import is_agreed, revise

# Escritas usadas pelas rotas e pelo comando que cria a viagem de demonstração.
# Validam formato e referências; quem decide é o motor.

TRIP_CLOSED = "A viagem já fechou: todos aceitaram o plano final."
OLD_ROUND = "Este plano é de uma rodada anterior. Veja a rodada mais recente."


def ensure_open(trip: models.Trip) -> None:
    """Depois do acordo, nada muda: nem respostas, nem reações, nem rodadas."""
    if trip.status == "agreed":
        raise HTTPException(409, TRIP_CLOSED)


def ensure_latest_round(session: Session, plan: models.Plan) -> None:
    if plan.round != queries.latest_round(session, plan.trip_id):
        raise HTTPException(409, OLD_ROUND)


def _check_destinations(
    destinations: list[models.CatalogDestination],
    items: list[schemas.HardConstraint | schemas.SoftConstraint],
) -> None:
    trip_ids = {row.id for row in destinations}
    cited = {destination_id for item in items for destination_id in getattr(item, "destination_ids", [])}
    if unknown := sorted(cited - trip_ids):
        raise HTTPException(422, f"Destino que não está na viagem: {', '.join(unknown)}.")


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
    _check_destinations(destinations, [*data.hard, *data.soft])
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
    ensure_open(trip)
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


def rejection_draft(
    session: Session, member: models.Member, comment: str, parser: ConstraintParser
) -> schemas.ConstraintDraft:
    """O que o motivo da recusa pede, interpretado como na tela Responder. Não salva nada."""
    trip = session.get_one(models.Trip, member.trip_id)
    parsed = parser.parse(comment, convert.parse_context(trip, queries.trip_destinations(session, trip.id)))
    return schemas.ConstraintDraft(
        hard=parsed.hard,
        soft=parsed.soft,
        member_limits=queries.own_limits(session, trip, member.id, convert.items_json(parsed.hard)),
    )


def confirm_rejection(
    session: Session, member: models.Member, plan: models.Plan, data: schemas.ConfirmRejectionInput
) -> models.ConstraintSet:
    """
    Grava a nova versão das restrições de quem recusou: as anteriores revistas
    pelo que a pessoa confirmou (engine/rounds.py). Vale a partir da próxima rodada.
    """
    reaction = queries.reactions_by_member(session, plan.id).get(member.id)
    if reaction is None or reaction.verdict != "rejected":
        raise HTTPException(409, "Só quem recusou este plano confirma uma restrição a partir do motivo.")
    previous = queries.latest_constraints(session, member.id)
    if previous and previous.confirmed_at >= reaction.reacted_at:
        raise HTTPException(409, "A restrição desta recusa já foi confirmada.")

    destinations = queries.trip_destinations(session, member.trip_id)
    _check_destinations(destinations, [*data.hard, *data.soft])
    version = (previous.version if previous else 0) + 1
    # Os ids do rascunho ganham a versão: nunca repetem os das restrições anteriores.
    added = convert.with_summaries(
        schemas.ConstraintsInput(
            raw_text=reaction.comment or "",
            hard=[item.model_copy(update={"id": f"v{version}-{item.id}"}) for item in data.hard],
            soft=[item.model_copy(update={"id": f"v{version}-{item.id}"}) for item in data.soft],
        ),
        destinations,
    )
    previous_hard = previous.hard if previous else []
    previous_soft = previous.soft if previous else []
    added_hard, added_soft = convert.items_json(added.hard), convert.items_json(added.soft)

    revised = revise(
        convert.engine_member(member.id, previous_hard, previous_soft, member.position),
        convert.engine_member(member.id, added_hard, added_soft, member.position),
    )
    by_id = {item["id"]: item for item in [*previous_hard, *previous_soft, *added_hard, *added_soft]}
    raw_text = f"Ao recusar um plano: {reaction.comment}"
    record = models.ConstraintSet(
        member_id=member.id,
        raw_text=f"{previous.raw_text}\n\n{raw_text}" if previous and previous.raw_text else raw_text,
        hard=[by_id[item.id] for item in revised.hard],
        soft=[by_id[item.id] for item in revised.soft],
        version=version,
    )
    session.add(record)
    session.flush()
    session.refresh(record)
    member.responded_at = record.confirmed_at
    return record


def update_agreement(session: Session, trip: models.Trip, plan: models.Plan) -> None:
    """Fecha a viagem quando todos que responderam aceitaram o recomendado da rodada mais recente."""
    if plan.position != 0:
        return
    verdicts = {
        member_id: row.verdict for member_id, row in queries.reactions_by_member(session, plan.id).items()
    }
    respondent_ids = [member.id for member, _ in queries.respondents(session, trip.id)]
    if is_agreed(respondent_ids, verdicts):
        trip.status = "agreed"
