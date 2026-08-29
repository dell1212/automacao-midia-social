from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCategory, ContentGenerationTemplate, ContentPieceType
from app.services.content.campaigns import get_campaign


def create_template(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    type: ContentPieceType,
    generation_prompt: Optional[str],
    avatar_id: Optional[int],
    voice_id: Optional[str],
    is_synthetic_media: bool,
    content_category: Optional[ContentCategory],
    aspect_ratio: str,
    resolution: Optional[str],
    duration: Optional[int],
) -> Optional[ContentGenerationTemplate]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return None
    template = ContentGenerationTemplate(
        campaign_id=campaign_id,
        type=type,
        generation_prompt=generation_prompt,
        avatar_id=avatar_id,
        voice_id=voice_id,
        is_synthetic_media=is_synthetic_media,
        content_category=content_category,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def list_templates(
    session: Session, *, tenant_id: int, campaign_id: int
) -> List[ContentGenerationTemplate]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    return list(
        session.exec(
            select(ContentGenerationTemplate).where(
                ContentGenerationTemplate.campaign_id == campaign_id
            )
        ).all()
    )
