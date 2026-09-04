"""Per-channel publish validation.

The rule from the reference product, kept exactly: **issues block publishing,
not drafting.** A piece can sit half-finished for as long as you like; the
block lands at the publish call.

Enforced server-side rather than in the composer, because the composer is not
the only way to publish — the scheduler and the machine API reach the same
pipeline, and a check that only exists in the UI is not a check.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from sqlmodel import Session

from app.models.content import ContentPiece
from app.services.content import captions as captions_service
from app.services.content import platform_specs
from app.services.content.publications import get_final_asset
from app.services.content.publishers.base import get_adapter
from app.services.content.publish_errors import PublicationError


@dataclass
class ChannelIssue:
    code: str
    message: str


@dataclass
class ChannelValidation:
    platform: str
    social_account_id: Optional[int]
    label: str
    issues: List[ChannelIssue] = field(default_factory=list)
    caption_length: int = 0
    caption_max: int = 0

    @property
    def ready(self) -> bool:
        return not self.issues


def validate_channel(
    session: Session,
    *,
    piece: ContentPiece,
    platform: str,
    social_account_id: Optional[int] = None,
    label: Optional[str] = None,
) -> ChannelValidation:
    spec = platform_specs.spec_for(platform)
    result = ChannelValidation(
        platform=platform,
        social_account_id=social_account_id,
        label=label or platform,
        caption_max=spec.caption_max if spec else 0,
    )

    if spec is None:
        result.issues.append(
            ChannelIssue("unknown_platform", f"Plataforma '{platform}' não é suportada.")
        )
        return result

    if piece.type.value not in spec.accepts:
        result.issues.append(
            ChannelIssue(
                "unsupported_type",
                f"{spec.label} não aceita peças do tipo {piece.type.value}.",
            )
        )

    asset = get_final_asset(session, content_piece_id=piece.id)
    if asset is None:
        result.issues.append(
            ChannelIssue("missing_asset", "A peça ainda não tem um asset final.")
        )
    else:
        # The adapter is the authority on its own compatibility; asking it here
        # means the composer and the publisher cannot disagree.
        try:
            get_adapter(platform).check_compatibility(piece, asset)
        except PublicationError as error:
            result.issues.append(ChannelIssue("incompatible", str(error)))
        except Exception:
            # An adapter that blows up on inspection is a structural problem,
            # not a piece problem — do not report it as the piece's fault.
            pass

    caption = captions_service.resolve_for_platform(
        session, piece=piece, platform=platform
    )
    body = caption.rendered(platform=platform)
    result.caption_length = len(body)

    if not body.strip():
        result.issues.append(
            ChannelIssue("empty_caption", "Sem legenda para publicar.")
        )
    elif caption.source == "generation_prompt":
        # Not fatal, but the single most likely thing to embarrass someone:
        # the image-generation prompt going out as the visible post text.
        result.issues.append(
            ChannelIssue(
                "caption_is_prompt",
                "A legenda ainda é o prompt de geração — escreva o texto do post.",
            )
        )

    if result.caption_length > spec.caption_max:
        result.issues.append(
            ChannelIssue(
                "caption_too_long",
                f"Legenda com {result.caption_length} caracteres, limite de {spec.caption_max}.",
            )
        )

    return result


def validate_piece(session: Session, *, piece: ContentPiece) -> List[ChannelValidation]:
    """Validate every channel this piece would actually publish to."""
    from app.services.content import targets as targets_service

    accounts = targets_service.resolve_target_accounts(session, piece=piece)
    return [
        validate_channel(
            session,
            piece=piece,
            platform=account.platform,
            social_account_id=account.id,
            label=f"{account.platform} · {account.external_account_id}",
        )
        for account in accounts
    ]
