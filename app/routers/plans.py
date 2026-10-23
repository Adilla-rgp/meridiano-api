from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func

from app import models, queries, schemas
from app.deps import SessionDep, find_member_by_token

router = APIRouter(tags=["planos"])

MIN_REACTION_COMMENT_LENGTH = 3


@router.post("/plans/{plan_id}/reactions", response_model=schemas.Reaction, status_code=201)
def react(plan_id: str, data: schemas.CreateReactionInput, session: SessionDep):
    """Cria ou substitui a reação do convidado ao plano. O convidado se identifica pelo token do convite."""
    member = find_member_by_token(session, data.invite_token)
    plan = session.get(models.Plan, plan_id)
    if plan is None or plan.trip_id != member.trip_id:
        raise HTTPException(404, "Plano não encontrado.")
    if plan.round != queries.latest_round(session, plan.trip_id):
        raise HTTPException(409, "Este plano é de uma rodada anterior. Veja a rodada mais recente.")

    comment = (data.comment or "").strip() or None
    if data.verdict != "accepted" and len(comment or "") < MIN_REACTION_COMMENT_LENGTH:
        message = (
            "Conte o motivo da recusa." if data.verdict == "rejected" else "Conte qual é a sua ressalva."
        )
        raise HTTPException(422, message)

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
    session.commit()
    return schemas.Reaction.model_validate(reaction)
