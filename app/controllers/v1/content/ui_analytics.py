from datetime import datetime

from fastapi import Depends, Query
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content_analytics import AnalyticsOverview
from app.services.content import ui_analytics as ui_analytics_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/analytics/overview", response_model=AnalyticsOverview)
def get_analytics_overview(
    date_from: datetime = Query(alias="from"),
    date_to: datetime = Query(alias="to"),
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Every number the dashboard shows, in one response.

    Deliberately one fat payload rather than six endpoints: split up, the
    screen assembles itself in six visible stages, which looks broken during a
    live demo and gives six chances to half-fail.
    """
    return ui_analytics_service.get_overview(
        session,
        tenant_id=user_session.tenant.id,
        date_from=date_from,
        date_to=date_to,
    )
