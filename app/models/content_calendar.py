from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel

from app.models.content import ContentPieceStatus, ContentPieceType


class CalendarState(str, Enum):
    """The vocabulary a calendar speaks, derived on read from
    `ContentPiece.status` + `scheduled_for` + `publication_summary`.

    Deliberately NOT added to ContentPieceStatus: the scheduler and the publish
    dispatcher both branch on that enum, so widening it to carry presentation
    states would put display concerns inside the state machine they depend on.
    Mapping vocabularies in the read layer costs nothing by comparison.
    """

    draft = "draft"
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"


class CalendarPlatformRead(BaseModel):
    platform: str
    # succeeded / failed / pending, summarised per platform. Read straight off
    # ContentPiece.publication_summary, which the dispatcher already maintains.
    succeeded: int = 0
    failed: int = 0


class CalendarItemRead(BaseModel):
    id: int
    campaign_id: int
    campaign_name: Optional[str]
    client_id: Optional[int]
    client_name: Optional[str]
    type: ContentPieceType
    status: ContentPieceStatus
    calendar_state: CalendarState
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    title: str
    thumbnail_url: Optional[str]
    platforms: List[CalendarPlatformRead]
    # True once any publication row exists for the piece: the publish pipeline
    # has taken over and the schedule is no longer the thing that decides when
    # it goes out. Computed server-side because the client cannot see those
    # rows without another round trip.
    is_locked: bool


class CalendarRangeRead(BaseModel):
    date_from: datetime
    date_to: datetime


class CalendarResponse(BaseModel):
    range: CalendarRangeRead
    # Counts are computed over the range BEFORE the status filter is applied,
    # so the filter pills keep showing what each option would yield rather than
    # collapsing to the current selection.
    counts: Dict[str, int]
    items: List[CalendarItemRead]


class CalendarFilterOption(BaseModel):
    id: str
    label: str


class CalendarFiltersResponse(BaseModel):
    clients: List[CalendarFilterOption]
    campaigns: List[CalendarFilterOption]
    platforms: List[CalendarFilterOption]
    accounts: List[CalendarFilterOption]


class PieceScheduleUpdate(BaseModel):
    """Body of PATCH /content/ui/pieces/{id}/schedule.

    `scheduled_for` is Optional AND meaningful when null: unlike PieceUpdate,
    where None means "leave unchanged", null here means "unschedule". The route
    inspects `model_fields_set` to tell an omitted field from an explicit null.
    """

    scheduled_for: Optional[datetime] = None
