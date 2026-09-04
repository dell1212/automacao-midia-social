from datetime import datetime
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session, select

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    ContentPiece,
    ContentPieceRead,
    ContentPieceStatus,
    PieceUpdate,
)
from app.models.content_calendar import PieceScheduleUpdate
from app.models.content_generation import ContentAssetType
from app.models.content_publishing import PublishRequest, PublishResponse
from app.models.content_ui import (
    AuditLogEntryRead,
    CaptionSuggestRequest,
    CaptionUpsert,
    ChannelIssueRead,
    ChannelValidationRead,
    NextSlotRead,
    PieceCaptionRead,
    PieceDetailRead,
    PieceTargetOption,
    PieceTargetsRead,
    PieceTargetsUpdate,
    ResolvedCaptionRead,
    UserSessionRead,
)
from app.services import llm
from app.services.content import assets as assets_service
from app.services.content import audit
from app.services.content import automation_scheduler
from app.services.content import avatars as avatars_service
from app.services.content import campaigns as campaigns_service
from app.services.content import captions as captions_service
from app.services.content import pieces as pieces_service
from app.services.content import platform_specs
from app.services.content import publications as publications_service
from app.services.content import storage
from app.services.content import targets as targets_service
from app.services.content import ui_pieces as ui_pieces_service
from app.services.content import validation as validation_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/session", response_model=UserSessionRead)
def get_session_info(
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return UserSessionRead(
        tenant_id=user_session.tenant.id,
        tenant_name=user_session.tenant.name,
        user_id=user_session.user_id,
        role=user_session.role,
        name=user_session.name,
    )


@router.get("/content/ui/pieces", response_model=list[ContentPieceRead])
def list_pieces(
    campaign_id: int,
    status: Optional[ContentPieceStatus] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return pieces_service.list_pieces(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=campaign_id,
        status=status,
    )


@router.get("/content/ui/pieces/{piece_id}", response_model=PieceDetailRead)
def get_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    detail = ui_pieces_service.get_piece_detail(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return detail


@router.patch("/content/ui/pieces/{piece_id}", response_model=ContentPieceRead)
def update_piece(
    piece_id: int,
    payload: PieceUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to edit"
        )

    if payload.avatar_id is not None and avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=payload.avatar_id
    ) is None:
        raise HTTPException(status_code=422, detail="avatar_id not found in this tenant")

    result = pieces_service.update_piece(
        session,
        tenant_id=user_session.tenant.id,
        piece_id=piece_id,
        generation_prompt=payload.generation_prompt,
        narration_script=payload.narration_script,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        content_category=payload.content_category,
        risk_level=payload.risk_level,
        scheduled_for=payload.scheduled_for,
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the edit was applied"
        )
    updated, diff = result

    if diff:
        audit.write_audit_log(
            session,
            tenant_id=user_session.tenant.id,
            entity_type="content_piece",
            entity_id=piece_id,
            action="edited",
            actor=f"user:{user_session.user_id}",
            details=diff,
        )
    return updated


@router.patch(
    "/content/ui/pieces/{piece_id}/schedule", response_model=ContentPieceRead
)
def reschedule_piece(
    piece_id: int,
    payload: PieceScheduleUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Move or clear a piece's schedule, leaving its approval alone.

    Separate from PATCH /pieces/{id} on purpose: that route resets an approved
    piece to pending_approval on any edit, which is right for content changes
    and wrong for a calendar drag — it would quietly pull the piece out of the
    dispatch queue. Here `scheduled_for: null` means unschedule, whereas on the
    edit route None means "leave unchanged".
    """
    content_auth.require_role(user_session, "admin")

    if "scheduled_for" not in payload.model_fields_set:
        raise HTTPException(status_code=422, detail="scheduled_for is required")

    has_publications = publications_service.count_publications_for_piece(
        session, content_piece_id=piece_id
    ) > 0

    outcome, piece, diff = pieces_service.reschedule_piece(
        session,
        tenant_id=user_session.tenant.id,
        piece_id=piece_id,
        scheduled_for=payload.scheduled_for,
        has_publications=has_publications,
    )

    if outcome is pieces_service.RescheduleOutcome.not_found:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if outcome is pieces_service.RescheduleOutcome.locked:
        raise HTTPException(
            status_code=409,
            detail="schedule_locked: piece has already been dispatched for publishing",
        )
    if outcome is pieces_service.RescheduleOutcome.in_past:
        raise HTTPException(
            status_code=422,
            detail="scheduled_in_past: an approved piece cannot be scheduled in the past",
        )

    if diff:
        audit.write_audit_log(
            session,
            tenant_id=user_session.tenant.id,
            entity_type="content_piece",
            entity_id=piece_id,
            action="rescheduled",
            actor=f"user:{user_session.user_id}",
            details=diff,
        )
    return piece


@router.post("/content/ui/pieces/{piece_id}/approve", response_model=ContentPieceRead)
def approve_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.approve_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        # `piece` is the pre-transition read — a concurrent change is exactly
        # why this branch was reached, so re-fetch instead of reporting the
        # status that lost the race.
        current = pieces_service.get_piece(
            session, tenant_id=user_session.tenant.id, piece_id=piece_id
        ) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to approve, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="approved",
        actor=f"user:{user_session.user_id}",
    )
    return updated


@router.post("/content/ui/pieces/{piece_id}/reject", response_model=ContentPieceRead)
def reject_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.reject_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        current = pieces_service.get_piece(
            session, tenant_id=user_session.tenant.id, piece_id=piece_id
        ) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to reject, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="rejected",
        actor=f"user:{user_session.user_id}",
    )
    return updated


@router.post("/content/ui/pieces/{piece_id}/asset", response_model=ContentPieceRead)
async def replace_piece_asset(
    piece_id: int,
    type: ContentAssetType = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to replace its asset"
        )
    if type.value != piece.type.value:
        raise HTTPException(
            status_code=422,
            detail=f"asset type '{type.value}' does not match piece type '{piece.type.value}'",
        )

    campaign = campaigns_service.get_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=piece.campaign_id
    )

    data = await file.read()
    uploaded = storage.upload_bytes(
        tenant_id=user_session.tenant.id,
        path_prefix=str(piece_id),
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )

    result = pieces_service.mark_asset_replaced(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the asset was replaced"
        )
    updated, diff = result

    archived = assets_service.archive_assets_of_type(
        session, content_piece_id=piece_id, asset_type=type
    )
    new_asset = assets_service.create_manual_asset(
        session,
        tenant_id=user_session.tenant.id,
        client_id=campaign.client_id,
        content_piece_id=piece_id,
        asset_type=type,
        uploaded=uploaded,
        mime_type=file.content_type,
    )

    diff["asset"] = {
        "before": archived[0].storage_path if archived else None,
        "after": new_asset.storage_path,
    }
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="asset_replaced",
        actor=f"user:{user_session.user_id}",
        details=diff,
    )
    return updated


@router.get("/content/ui/audit-log", response_model=list[AuditLogEntryRead])
def list_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    since: Optional[datetime] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return audit.list_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type=entity_type,
        entity_id=entity_id,
        since=since,
        limit=limit,
        offset=offset,
    )


# --- Captions and publishing -------------------------------------------
#
# Before these routes existed the SPA could approve a piece but never publish
# it (POST /content/pieces/{id}/publish is tenant-token only), and the text
# that went out was piece.generation_prompt — the image-generation prompt.


@router.get(
    "/content/ui/platform-specs", response_model=list[platform_specs.PlatformSpec]
)
def list_platform_specs():
    """Per-platform limits, so the composer's character counter cannot drift
    from what the publisher actually accepts."""
    return platform_specs.all_specs()


@router.get(
    "/content/ui/pieces/{piece_id}/captions", response_model=list[PieceCaptionRead]
)
def list_piece_captions(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return [
        PieceCaptionRead(
            platform=row.platform,
            title=row.title,
            body=row.body,
            hashtags=list(row.hashtags or []),
            link_url=row.link_url,
            is_override=row.is_override,
        )
        for row in captions_service.list_captions(session, content_piece_id=piece_id)
    ]


@router.put(
    "/content/ui/pieces/{piece_id}/captions", response_model=PieceCaptionRead
)
def upsert_piece_caption(
    piece_id: int,
    payload: CaptionUpsert,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to edit its caption"
        )
    if payload.platform is not None and platform_specs.spec_for(payload.platform) is None:
        raise HTTPException(status_code=422, detail="unknown platform")

    row = captions_service.upsert_caption(
        session,
        content_piece_id=piece_id,
        platform=payload.platform,
        title=payload.title,
        body=payload.body,
        hashtags=payload.hashtags,
        link_url=payload.link_url,
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="caption_edited",
        actor=f"user:{user_session.user_id}",
        details={"platform": payload.platform},
    )
    return PieceCaptionRead(
        platform=row.platform,
        title=row.title,
        body=row.body,
        hashtags=list(row.hashtags or []),
        link_url=row.link_url,
        is_override=row.is_override,
    )


@router.delete(
    "/content/ui/pieces/{piece_id}/captions/{platform}", status_code=204
)
def delete_piece_caption_override(
    piece_id: int,
    platform: str,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """"Use global content": drops a platform override so it falls back."""
    content_auth.require_role(user_session, "admin")

    if pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    ) is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    captions_service.delete_override(
        session, content_piece_id=piece_id, platform=platform
    )
    return None


@router.get(
    "/content/ui/pieces/{piece_id}/captions/resolved",
    response_model=list[ResolvedCaptionRead],
)
def resolve_piece_captions(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """What each platform would actually publish right now.

    Drives the composer's per-channel counters and validation badges from the
    same resolution the dispatcher uses, so the preview cannot disagree with
    what goes out.
    """
    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    resolved = []
    for spec in platform_specs.all_specs():
        caption = captions_service.resolve_for_platform(
            session, piece=piece, platform=spec.platform
        )
        body = caption.rendered(platform=spec.platform)
        resolved.append(
            ResolvedCaptionRead(
                platform=spec.platform,
                body=body,
                source=caption.source,
                length=len(body),
                caption_max=spec.caption_max,
                over_limit=len(body) > spec.caption_max,
            )
        )
    return resolved


@router.post(
    "/content/ui/pieces/{piece_id}/captions/suggest", response_model=PieceCaptionRead
)
def suggest_piece_caption(
    piece_id: int,
    payload: CaptionSuggestRequest,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """"Write with AI".

    Thin wrapper over llm.generate_social_metadata, which already handles the
    hard parts — prompt construction, JSON repair, per-platform clamping,
    hashtag normalisation and a deterministic fallback when the LLM is
    unavailable. Returns a suggestion without saving it: the human approves.
    """
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    metadata = llm.generate_social_metadata(
        video_subject=piece.generation_prompt or f"Peça {piece.id}",
        video_script=piece.narration_script or "",
        language=payload.language,
        platform=platform_specs.llm_platform_for(payload.platform or "instagram"),
    )
    return PieceCaptionRead(
        platform=payload.platform,
        title=metadata.get("title"),
        body=metadata.get("caption"),
        hashtags=list(metadata.get("hashtags") or []),
        link_url=None,
        is_override=payload.platform is not None,
    )


@router.post("/content/ui/pieces/{piece_id}/publish", response_model=PublishResponse)
def publish_piece(
    piece_id: int,
    payload: PublishRequest,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Publish now, from the UI.

    The same resolve_publication_request the machine API and the scheduler use
    — this route only adds the session/role check the tenant-token version
    does not need.
    """
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status not in (ContentPieceStatus.approved, ContentPieceStatus.posted):
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be approved to publish, got '{piece.status.value}'",
        )
    if not payload.social_account_ids:
        raise HTTPException(status_code=422, detail="social_account_ids must not be empty")

    # "Issues block publishing, not drafting." Enforced here rather than in the
    # composer because the composer is not the only path to this pipeline — the
    # scheduler and the machine API reach it too, and a check that lives only in
    # the UI is not a check.
    account_ids = list(dict.fromkeys(payload.social_account_ids))
    blocking = []
    for account in targets_service.list_available_accounts(session, piece=piece):
        if account.id not in account_ids:
            continue
        result = validation_service.validate_channel(
            session,
            piece=piece,
            platform=account.platform,
            social_account_id=account.id,
            label=f"{account.platform} · {account.external_account_id}",
        )
        # A caption still falling back to the generation prompt is a warning in
        # the composer, not a hard block: it publishes something coherent, just
        # not what anyone wrote. Everything else stops the publish.
        real_issues = [i for i in result.issues if i.code != "caption_is_prompt"]
        if real_issues:
            blocking.append(
                {"platform": account.platform, "issues": [i.message for i in real_issues]}
            )
    if blocking:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_failed", "channels": blocking},
        )

    accepted, rejected = publications_service.resolve_publication_request(
        session, piece=piece, social_account_ids=account_ids
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="publish_requested",
        actor=f"user:{user_session.user_id}",
        details={"accepted": len(accepted), "rejected": len(rejected)},
    )
    return PublishResponse(accepted=accepted, rejected=rejected)


# --- Composer: targeting, validation, scheduling helper -----------------


@router.get("/content/ui/pieces/{piece_id}/targets", response_model=PieceTargetsRead)
def get_piece_targets(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    available = targets_service.list_available_accounts(session, piece=piece)
    selected = {
        row.social_account_id
        for row in targets_service.list_targets(session, content_piece_id=piece_id)
    }
    return PieceTargetsRead(
        is_targeted=bool(selected),
        options=[
            PieceTargetOption(
                social_account_id=account.id,
                platform=account.platform,
                label=account.external_account_id,
                # With no targeting every account is in scope, so they all show
                # as selected — that is the truth of what would publish.
                selected=(account.id in selected) if selected else True,
            )
            for account in available
        ],
    )


@router.put("/content/ui/pieces/{piece_id}/targets", response_model=PieceTargetsRead)
def set_piece_targets(
    piece_id: int,
    payload: PieceTargetsUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to change its channels"
        )

    available = targets_service.list_available_accounts(session, piece=piece)
    all_ids = {account.id for account in available}
    # Selecting every account is the same as no targeting; storing rows for it
    # would silently freeze the piece against accounts added later.
    wanted = set(payload.social_account_ids) & all_ids
    targets_service.set_targets(
        session,
        piece=piece,
        social_account_ids=[] if wanted == all_ids else sorted(wanted),
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="targets_changed",
        actor=f"user:{user_session.user_id}",
        details={"accounts": len(wanted) if wanted != all_ids else "todas"},
    )
    return get_piece_targets(piece_id, session=session, user_session=user_session)


@router.get(
    "/content/ui/pieces/{piece_id}/validation",
    response_model=list[ChannelValidationRead],
)
def validate_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """Per-channel readiness, using the same checks the publish route enforces."""
    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    return [
        ChannelValidationRead(
            platform=result.platform,
            social_account_id=result.social_account_id,
            label=result.label,
            ready=result.ready,
            issues=[
                ChannelIssueRead(code=issue.code, message=issue.message)
                for issue in result.issues
            ],
            caption_length=result.caption_length,
            caption_max=result.caption_max,
        )
        for result in validation_service.validate_piece(session, piece=piece)
    ]


@router.get("/content/ui/pieces/{piece_id}/next-slot", response_model=NextSlotRead)
def get_next_slot(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    """"Next available slot": one day after the campaign's latest scheduled
    piece, mirroring the cadence the automation scheduler already uses so a
    manual schedule does not collide with the proactive one."""
    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    latest = session.exec(
        select(ContentPiece.scheduled_for)
        .where(
            ContentPiece.campaign_id == piece.campaign_id,
            ContentPiece.scheduled_for != None,  # noqa: E711
            ContentPiece.status.notin_(
                [ContentPieceStatus.rejected, ContentPieceStatus.failed]
            ),
        )
        .order_by(ContentPiece.scheduled_for.desc())
        .limit(1)
    ).first()

    return NextSlotRead(
        scheduled_for=automation_scheduler.next_slot(latest, now=datetime.utcnow())
    )
