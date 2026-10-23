from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_session
from app.parsing import ConstraintParser, get_parser
from app.security import hash_token, token_matches

# Autenticação do MVP, sem login: o organizador manda o admin_token no
# cabeçalho X-Admin-Token; o convidado usa o invite_token do link (no caminho
# das rotas /invite e no corpo da reação, como no contrato).

SessionDep = Annotated[Session, Depends(get_session)]

ADMIN_HEADER = "X-Admin-Token"
INVITE_HEADER = "X-Invite-Token"


def not_found(message: str) -> HTTPException:
    return HTTPException(404, message)


def find_trip(session: Session, trip_id: str) -> models.Trip:
    trip = session.get(models.Trip, trip_id)
    if trip is None:
        raise not_found("Viagem não encontrada.")
    return trip


def find_member_by_token(session: Session, token: str) -> models.Member:
    member = session.scalars(
        select(models.Member).where(models.Member.invite_token_hash == hash_token(token))
    ).first()
    if member is None:
        raise not_found("Convite não encontrado.")
    return member


def require_admin(
    trip_id: str,
    session: SessionDep,
    admin_token: Annotated[str | None, Header(alias=ADMIN_HEADER)] = None,
) -> models.Trip:
    trip = find_trip(session, trip_id)
    if not admin_token:
        raise HTTPException(401, "Esta ação é do organizador: envie o token de administração.")
    if not token_matches(admin_token, trip.admin_token_hash):
        raise HTTPException(403, "Token de administração inválido para esta viagem.")
    return trip


AdminTrip = Annotated[models.Trip, Depends(require_admin)]


def invite_member(token: str, session: SessionDep) -> models.Member:
    return find_member_by_token(session, token)


InviteMember = Annotated[models.Member, Depends(invite_member)]


def parser(request: Request) -> ConstraintParser:
    return get_parser(request.app.state.settings.constraint_parser)


ParserDep = Annotated[ConstraintParser, Depends(parser)]
