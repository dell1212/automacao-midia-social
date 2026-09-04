from datetime import datetime
from typing import List, Optional

from fastapi import Depends, Query
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content_calendar import (
    CalendarFiltersResponse,
    CalendarResponse,
    CalendarState,
)
from app.services.content import ui_calendar as ui_calendar_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/calendar", response_model=CalendarResponse)
def get_calendar(
    # `from`/`to` are the natural names but `from` is a Python keyword, so the
    # wire contract keeps them and the parameters are aliased.
    date_from: datetime = Query(alias="from"),
    date_to: datetime = Query(alias="to"),
    client_id: Optional[int] = None,
    campaign_id: Optional[List[int]] = Query(default=None),
    state: Optional[List[CalendarState]] = Query(default=None),
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Pieces positioned on the calendar between `from` and `to`.

    Tenant-scoped rather than campaign-scoped: unlike GET /content/ui/pieces,
    a calendar has to show every campaign at once.
    """
    return ui_calendar_service.get_calendar(
        session,
        tenant_id=user_session.tenant.id,
        date_from=date_from,
        date_to=date_to,
        client_id=client_id,
        campaign_ids=campaign_id,
        states=state,
    )


@router.get("/content/ui/calendar/filters", response_model=CalendarFiltersResponse)
def get_calendar_filters(
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return ui_calendar_service.get_filters(session, tenant_id=user_session.tenant.id)
