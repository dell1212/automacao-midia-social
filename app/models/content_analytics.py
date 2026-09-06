from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AnalyticsTiles(BaseModel):
    published: int
    scheduled: int
    failed: int
    # Reach (unique people) only exists on Instagram/Facebook; the other
    # four platforms only publish impressions (exposure volume, not people).
    # None when no publication in the window has a snapshot with any metric
    # yet — not zero, which would read as "the campaign got zero reach"
    # instead of "nothing collected yet".
    reach: Optional[int] = None
    interactions: Optional[int] = None
    # None whenever reach is unknown or sums to zero — a rate over zero reach
    # is not 0%, it is undefined.
    engagement_rate: Optional[float] = None
    # How many distinct social accounts in this window had their reach
    # substituted by impressions, because their platform has no unique-reach
    # metric. Feeds the reach tile's hint so the substitution stays visible
    # rather than silently blending into one number.
    reach_substituted_accounts: int = 0


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
