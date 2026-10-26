from fastapi import APIRouter, Depends, HTTPException, Request

from app import convert, models, queries, schemas, services
from app.deps import InviteMember, ParserDep, SessionDep, limit_parse

router = APIRouter(tags=["convites"])

MIN_RAW_TEXT_LENGTH = 10


@router.get("/invite/{token}", response_model=schemas.Invite)
def get_invite(member: InviteMember, session: SessionDep, request: Request):
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
        member_limits=queries.own_limits(session, trip, member.id, record.hard) if record else [],
        latest_round=queries.latest_round(session, trip.id),
        constraint_parser=request.app.state.settings.constraint_parser,
    )


@router.post(
    "/invite/{token}/constraints/parse",
    response_model=schemas.ParsedConstraints,
    dependencies=[Depends(limit_parse)],
)
def parse_constraints(data: schemas.ParseInput, member: InviteMember, session: SessionDep, parser: ParserDep):
    """Interpreta o texto livre. Não salva: a pessoa confirma e envia por PUT."""
    if len(data.raw_text) < MIN_RAW_TEXT_LENGTH:
        raise HTTPException(422, "Escreva um pouco mais sobre suas condições para que possamos interpretar.")
    trip = session.get_one(models.Trip, member.trip_id)
    services.ensure_open(trip)
    destinations = queries.trip_destinations(session, trip.id)
    parsed = parser.parse(data.raw_text, convert.parse_context(trip, destinations))
    return schemas.ParsedConstraints(
        **parsed.model_dump(),
        member_limits=queries.own_limits(session, trip, member.id, convert.items_json(parsed.hard)),
    )


@router.put("/invite/{token}/constraints", response_model=schemas.Constraints)
def save_constraints(data: schemas.ConstraintsInput, member: InviteMember, session: SessionDep):
    services.ensure_open(session.get_one(models.Trip, member.trip_id))
    record = services.save_constraints(session, member, data)
    session.commit()
    return schemas.Constraints.model_validate(record)
