from dataclasses import dataclass
from typing import Optional

from app.models.content import ContentCategory, RiskLevel

# Bump this whenever _CATEGORY_RISK changes. Pieces keep the version they were
# classified under, so an updated table never silently reclassifies history.
POLICY_VERSION = "v1"

# Static, deterministic, no external call and no AI. Risk here reflects how
# tightly the niche is regulated in advertising, not the quality of any
# specific piece — classification, never enforcement.
_CATEGORY_RISK: dict[ContentCategory, RiskLevel] = {
    ContentCategory.medical: RiskLevel.high,
    ContentCategory.pharmaceutical: RiskLevel.high,
    ContentCategory.gambling: RiskLevel.high,
    ContentCategory.political: RiskLevel.high,
    ContentCategory.financial: RiskLevel.medium,
    ContentCategory.insurance: RiskLevel.medium,
    ContentCategory.legal: RiskLevel.medium,
    ContentCategory.alcohol: RiskLevel.medium,
    ContentCategory.regulated_product: RiskLevel.medium,
}


@dataclass(frozen=True)
class PolicyClassification:
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str


def risk_for_category(category: Optional[ContentCategory]) -> RiskLevel:
    if category is None:
        return RiskLevel.none
    return _CATEGORY_RISK.get(category, RiskLevel.medium)


def classify(category: Optional[ContentCategory]) -> PolicyClassification:
    """Derive the policy fields persisted on a ContentPiece at creation time.

    This phase records only. Nothing here blocks generation, upload or
    publishing — `requires_human_review` exists so a future policy engine can
    read it without a migration.
    """
    risk = risk_for_category(category)
    return PolicyClassification(
        risk_level=risk,
        requires_human_review=risk == RiskLevel.high,
        policy_version=POLICY_VERSION,
    )
