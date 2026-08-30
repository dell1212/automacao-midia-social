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
            select(ContentGenerationTemplate)
            .where(ContentGenerationTemplate.campaign_id == campaign_id)
            # pick_template_index rotates by position, so the rotation is only
            # deterministic if the row order is stable across calls — without
            # an ORDER BY, Postgres is free to return them in any order.
            .order_by(ContentGenerationTemplate.id)
        ).all()
    )


def get_template(
    session: Session, *, tenant_id: int, template_id: int
) -> Optional[ContentGenerationTemplate]:
    template = session.exec(
        select(ContentGenerationTemplate).where(ContentGenerationTemplate.id == template_id)
    ).first()
    if template is None:
        return None
    if get_campaign(session, tenant_id=tenant_id, campaign_id=template.campaign_id) is None:
        return None
    return template


def update_template(
    session: Session,
    *,
    tenant_id: int,
    template_id: int,
    generation_prompt: Optional[str] = None,
    avatar_id: Optional[int] = None,
    voice_id: Optional[str] = None,
    is_synthetic_media: Optional[bool] = None,
    content_category: Optional[ContentCategory] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
) -> Optional[ContentGenerationTemplate]:
    template = get_template(session, tenant_id=tenant_id, template_id=template_id)
    if template is None:
        return None
    if generation_prompt is not None:
        template.generation_prompt = generation_prompt
    if avatar_id is not None:
        template.avatar_id = avatar_id
    if voice_id is not None:
        template.voice_id = voice_id
    if is_synthetic_media is not None:
        template.is_synthetic_media = is_synthetic_media
    if content_category is not None:
        template.content_category = content_category
    if aspect_ratio is not None:
        template.aspect_ratio = aspect_ratio
    if resolution is not None:
        template.resolution = resolution
    if duration is not None:
        template.duration = duration
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def deactivate_template(
    session: Session, *, tenant_id: int, template_id: int
) -> Optional[ContentGenerationTemplate]:
    template = get_template(session, tenant_id=tenant_id, template_id=template_id)
    if template is None:
        return None
    template.is_active = False
    session.add(template)
    session.commit()
    session.refresh(template)
    return template
