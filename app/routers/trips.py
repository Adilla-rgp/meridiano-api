from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app import convert, models, queries, schemas, services
from app.deps import (
    ADMIN_HEADER,
    INVITE_HEADER,
    AdminTrip,
    SessionDep,
    find_member_by_token,
    find_trip,
    limit_plans,
)
from app.security import token_matches
from engine.tensions import tensions

router = APIRouter(tags=["viagens"])


def admin_url(request: Request, trip_id: str, admin_token: str) -> str:
    """O token vai no fragmento (#), que o navegador não manda a servidores nem guarda em logs de acesso."""
    base = request.app.state.settings.front_base_url.rstrip("/")
    return f"{base}/viagens/{trip_id}/tensoes#admin={admin_token}"


@router.post("/trips", response_model=schemas.TripCreated, status_code=201)
def create_trip(data: schemas.CreateTripInput, session: SessionDep, request: Request):
    trip, admin_token, organizer_token = services.create_trip(session, data)
    session.commit()
    parser = request.app.state.settings.constraint_parser
    detail = queries.trip_detail(session, trip, parser, {trip.organizer_id or "": organizer_token})
    return schemas.TripCreated(
        **detail.model_dump(), admin_token=admin_token, admin_url=admin_url(request, trip.id, admin_token)
    )


@router.get("/trips/{trip_id}", response_model=schemas.TripDetail)
def get_trip(trip: AdminTrip, session: SessionDep, request: Request):
    return queries.trip_detail(session, trip, request.app.state.settings.constraint_parser)


@router.post("/trips/{trip_id}/members", response_model=list[schemas.Member], status_code=201)
def create_members(data: schemas.CreateMembersInput, trip: AdminTrip, session: SessionDep):
    created = services.add_members(session, trip, data.display_names)
    session.commit()
    return [queries.member_schema(member, token) for member, token in created]


@router.post("/trips/{trip_id}/members/{member_id}/invite", response_model=schemas.Member)
def reissue_invite(member_id: str, trip: AdminTrip, session: SessionDep):
    """Gera um novo link de convite para o participante; o anterior deixa de valer."""
    member = session.get(models.Member, member_id)
    if member is None or member.trip_id != trip.id:
        raise HTTPException(404, "Participante não encontrado.")
    token = services.reissue_invite(session, member)
    session.commit()
    return queries.member_schema(member, token)


@router.get("/trips/{trip_id}/tensions", response_model=schemas.TripTensions)
def get_tensions(trip: AdminTrip, session: SessionDep):
    members = queries.trip_members(session, trip.id)
    respondents = queries.respondents(session, trip.id)
    destinations = queries.trip_destinations(session, trip.id)
    result = tensions(
        convert.trip_input(trip, destinations, [member for _, member in respondents]),
        {member.id: member.display_name for member, _ in respondents},
    )
    return schemas.TripTensions(
        trip_id=trip.id,
        member_count=len(members),
        responded_count=len(respondents),
        most_restrictive_member_id=result.most_restrictive_member_id,
        pairs=[schemas.MemberPair.model_validate(item) for item in result.pairs],
        key_constraints=[schemas.KeyConstraint.model_validate(item) for item in result.key_constraints],
        viability=[schemas.DestinationViability.model_validate(item) for item in result.viability],
    )


@router.post(
    "/trips/{trip_id}/plans",
    response_model=schemas.PlanRound,
    status_code=201,
    dependencies=[Depends(limit_plans)],
)
def generate_plans(trip: AdminTrip, session: SessionDep):
    """Roda o motor de forma síncrona e grava a nova rodada."""
    round_number = services.generate_round(session, trip)
    session.commit()
    return queries.plan_round(session, trip.id, round_number, viewer_member_id=None)


@router.get("/trips/{trip_id}/plans", response_model=schemas.PlanRound)
def get_plans(
    trip_id: str,
    session: SessionDep,
    round_number: Annotated[int, Query(alias="round", ge=1)],
    admin_token: Annotated[str | None, Header(alias=ADMIN_HEADER)] = None,
    invite_token: Annotated[str | None, Header(alias=INVITE_HEADER)] = None,
):
    """Organizador (X-Admin-Token) vê todas as reações; convidado (X-Invite-Token), só as próprias."""
    trip = find_trip(session, trip_id)
    if admin_token:
        if not token_matches(admin_token, trip.admin_token_hash):
            raise HTTPException(403, "Token de administração inválido para esta viagem.")
        viewer = None
    elif invite_token:
        member = find_member_by_token(session, invite_token)
        if member.trip_id != trip.id:
            raise HTTPException(403, "Este convite é de outra viagem.")
        viewer = member.id
    else:
        raise HTTPException(401, "Envie o token de administração ou o do convite.")

    result = queries.plan_round(session, trip.id, round_number, viewer)
    if result is None:
        raise HTTPException(404, "Rodada não encontrada.")
    return result
