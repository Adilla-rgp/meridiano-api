from fastapi import APIRouter, HTTPException

from app import convert, models, queries, schemas, services
from app.deps import InviteMember, ParserDep, SessionDep
from app.parsing import ParseContext
from engine.privacy import limits_for_member

router = APIRouter(tags=["convites"])

MIN_RAW_TEXT_LENGTH = 10


def own_limits(
    session: SessionDep, trip: models.Trip, member_id: str, hard: list[dict]
) -> list[schemas.MemberLimit]:
    """O que cada limite desta pessoa elimina sozinho. Só para ela (engine/privacy.py)."""
    destinations = queries.trip_destinations(session, trip.id)
    member = convert.engine_member(member_id, hard, [])
    return [
        convert.member_limit(item)
        for item in limits_for_member(convert.trip_input(trip, destinations, [member]), member_id)
    ]


@router.get("/invite/{token}", response_model=schemas.Invite)
def get_invite(member: InviteMember, session: SessionDep):
    trip = session.get_one(models.Trip, member.trip_id)
    members = queries.trip_members(session, trip.id)
    organizer = next((item for item in members if item.is_organizer), None)
    record = queries.latest_constraints(session, member.id)
    return schemas.Invite(
        trip=schemas.Trip.model_validate(trip),
        member=queries.member_schema(member),
        organizer_name=organizer.display_name if organizer else "",
        member_count=len(members),
        members=[schemas.GroupMember.model_validate(item) for item in members],
        destinations=[
            convert.destination_schema(row, trip.nights)
            for row in queries.trip_destinations(session, trip.id)
        ],
        constraints=schemas.Constraints.model_validate(record) if record else None,
        member_limits=own_limits(session, trip, member.id, record.hard) if record else [],
        latest_round=queries.latest_round(session, trip.id),
    )


@router.post("/invite/{token}/constraints/parse", response_model=schemas.ParsedConstraints)
def parse_constraints(data: schemas.ParseInput, member: InviteMember, session: SessionDep, parser: ParserDep):
    """Interpreta o texto livre. Não salva: a pessoa confirma e envia por PUT."""
    if len(data.raw_text) < MIN_RAW_TEXT_LENGTH:
        raise HTTPException(422, "Escreva um pouco mais sobre suas condições para que possamos interpretar.")
    trip = session.get_one(models.Trip, member.trip_id)
    destinations = queries.trip_destinations(session, trip.id)
    context = ParseContext(
        window_start=trip.date_window_start,
        window_end=trip.date_window_end,
        nights=trip.nights,
        destinations=tuple(convert.engine_destination(row) for row in destinations),
    )
    parsed = parser.parse(data.raw_text, context)
    return schemas.ParsedConstraints(
        **parsed.model_dump(),
        member_limits=own_limits(session, trip, member.id, convert.items_json(parsed.hard)),
    )


@router.put("/invite/{token}/constraints", response_model=schemas.Constraints)
def save_constraints(data: schemas.ConstraintsInput, member: InviteMember, session: SessionDep):
    record = services.save_constraints(session, member, data)
    session.commit()
    return schemas.Constraints.model_validate(record)
