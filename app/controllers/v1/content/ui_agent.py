from typing import Optional

from fastapi import Depends, HTTPException, Query
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content_generation import GenerationJobRead
from app.models.content_ui import AgentBriefRequest, AuditLogEntryRead
from app.services.content import agent as agent_service
from app.services.content import audit
from app.services.content import jobs as jobs_service
from app.services.content import pieces as pieces_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])

# Everything the automation does is already recorded under one of these
# actors; the agent's activity feed is a view over that, not a new store.
_SYSTEM_ACTOR_PREFIX = "system:"


@router.get(
    "/content/ui/pieces/{piece_id}/jobs", response_model=list[GenerationJobRead]
)
def list_piece_jobs(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """The generation steps behind a piece — provider, model, attempt counts,
    duration and error.

    This data has always existed on ContentGenerationJob and was reachable
    only through the machine API, so the SPA could never show what the
    pipeline actually did.
    """
    if pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    ) is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return jobs_service.list_jobs_for_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )


@router.get("/content/ui/agent/activity", response_model=list[AuditLogEntryRead])
def list_agent_activity(
    limit: int = Query(50, le=200),
    offset: int = 0,
    entity_type: Optional[str] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """What the automation decided on its own, newest first."""
    return audit.list_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type=entity_type,
        actor_prefix=_SYSTEM_ACTOR_PREFIX,
        limit=limit,
        offset=offset,
    )


@router.post("/content/ui/agent/brief", response_model=agent_service.AgentProposal)
def brief_the_agent(
    payload: AgentBriefRequest,
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Turn a plain-language brief into a proposed plan.

    Proposes only — nothing is created, nothing is scheduled, no generation is
    paid for. The human reviews the proposal and decides.
    """
    content_auth.require_role(user_session, "admin")

    if not payload.brief.strip():
        raise HTTPException(status_code=422, detail="brief must not be empty")
    return agent_service.propose_from_brief(payload.brief)
