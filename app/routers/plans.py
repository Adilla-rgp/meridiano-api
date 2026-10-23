from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app import models, schemas, services
from app.deps import ParserDep, SessionDep, find_member_by_token

router = APIRouter(tags=["planos"])

MIN_REACTION_COMMENT_LENGTH = 3


def find_plan(session: Session, plan_id: str, member: models.Member) -> tuple[models.Plan, models.Trip]:
    """O plano, da viagem do convidado e da rodada mais recente, com a viagem travada para escrita."""
    plan = session.get(models.Plan, plan_id)
    if plan is None or plan.trip_id != member.trip_id:
        raise HTTPException(404, "Plano não encontrado.")
    trip = session.get_one(models.Trip, plan.trip_id, with_for_update=True)
    services.ensure_open(trip)
    services.ensure_latest_round(session, plan)
    return plan, trip


@router.post("/plans/{plan_id}/reactions", response_model=schemas.ReactionResult, status_code=201)
def react(
    plan_id: str, data: schemas.CreateReactionInput, session: SessionDep, parser: ParserDep, request: Request
):
    """
    Cria ou substitui a reação do convidado ao plano. O convidado se identifica
    pelo token do convite. Na recusa, devolve o motivo interpretado, para a pessoa
    confirmar em POST /plans/{id}/reactions/constraints.
    """
    member = find_member_by_token(session, data.invite_token)
    plan, trip = find_plan(session, plan_id, member)

    comment = (data.comment or "").strip() or None
    if data.verdict != "accepted" and len(comment or "") < MIN_REACTION_COMMENT_LENGTH:
        message = (
            "Conte o motivo da recusa." if data.verdict == "rejected" else "Conte qual é a sua ressalva."
        )
        raise HTTPException(422, message)

    draft = None
    if data.verdict == "rejected" and comment:
        # O motivo passa pela mesma interpretação do texto livre, com o mesmo limite.
        request.app.state.parse_limiter.check(data.invite_token)
        draft = services.rejection_draft(session, member, comment, parser)

    session.execute(
        delete(models.Reaction).where(
            models.Reaction.plan_id == plan.id, models.Reaction.member_id == member.id
        )
    )
    reaction = models.Reaction(
        plan_id=plan.id,
        member_id=member.id,
        verdict=data.verdict,
        comment=None if data.verdict == "accepted" else comment,
        reacted_at=func.now(),
    )
    session.add(reaction)
    session.flush()
    services.update_agreement(session, trip, plan)
    session.commit()
    return schemas.ReactionResult(
        **schemas.Reaction.model_validate(reaction).model_dump(),
        constraint_draft=draft,
        trip_status=trip.status,
    )


@router.post("/plans/{plan_id}/reactions/constraints", response_model=schemas.Constraints, status_code=201)
def confirm_rejection(plan_id: str, data: schemas.ConfirmRejectionInput, session: SessionDep):
    """
    Confirma o que o motivo da recusa pede. As restrições de quem recusou ganham
    uma nova versão, que entra na próxima rodada.
    """
    member = find_member_by_token(session, data.invite_token)
    plan, _ = find_plan(session, plan_id, member)
    record = services.confirm_rejection(session, member, plan, data)
    session.commit()
    return schemas.Constraints.model_validate(record)
