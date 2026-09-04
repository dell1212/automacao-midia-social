from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AnalyticsTiles(BaseModel):
    published: int
    scheduled: int
    failed: int
    # None when nothing resolved in the window — a rate over zero attempts is
    # not 0%, it is unknown, and rendering it as 0% would read as failure.
    success_rate: Optional[float]
    # Null on purpose, not zero: this system has never collected post-publish
    # telemetry. The UI renders these as "not collected yet".
    link_clicks: Optional[int] = None
    engagement: Optional[int] = None


class ThroughputBucket(BaseModel):
    day: str
    published: int
    failed: int
    success_rate: Optional[float]


class PlatformSlice(BaseModel):
    platform: str
    published: int
    failed: int


class CadenceBucket(BaseModel):
    hour: int
    published: int


class AccountPerformanceRead(BaseModel):
    social_account_id: int
    platform: str
    label: str
    published: int
    failed: int
    success_rate: Optional[float]


class AnalyticsWindow(BaseModel):
    best_hour: Optional[int]
    active_accounts: int
    total_pieces: int
    # What generating this content actually cost. The reference product has no
    # equivalent — it publishes media it did not generate.
    generation_cost: Optional[float]
    generation_currency: Optional[str]
    autoapproved_pct: Optional[float]


class AnalyticsOverview(BaseModel):
    date_from: datetime
    date_to: datetime
    tiles: AnalyticsTiles
    throughput: List[ThroughputBucket]
    platform_mix: List[PlatformSlice]
    cadence_by_hour: List[CadenceBucket]
    account_performance: List[AccountPerformanceRead]
    window: AnalyticsWindow
