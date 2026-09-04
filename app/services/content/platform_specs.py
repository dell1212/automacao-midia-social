"""Canonical publishing limits for the six platforms with a real adapter.

Server-truth on purpose: a character counter hardcoded in the frontend drifts
from what the publisher actually accepts, and the first symptom is a post that
the composer said was fine being rejected at publish time.

Note this is NOT `llm.SOCIAL_PLATFORMS`. That map keys on the short-video
surfaces the legacy MoneyPrinterTurbo pipeline targets — `youtube_shorts`,
`instagram_reels`, `facebook_reels` — and has no entry for LinkedIn or X at
all. It stays where it is, driving caption *generation*; this module drives
*validation*, and the two need a mapping rather than one reusing the other.
"""
from typing import Optional

from pydantic import BaseModel


class PlatformSpec(BaseModel):
    platform: str
    label: str
    caption_max: int
    title_max: Optional[int] = None
    # Accepted piece types, matching ContentPieceType values.
    accepts: list[str]
    requires_media: bool = True
    hashtag_suggestion: int = 5


SPECS: dict[str, PlatformSpec] = {
    "x": PlatformSpec(
        platform="x",
        label="X",
        caption_max=280,
        accepts=["image", "video"],
        hashtag_suggestion=2,
    ),
    "linkedin": PlatformSpec(
        platform="linkedin",
        label="LinkedIn",
        caption_max=3000,
        accepts=["image", "video"],
        hashtag_suggestion=3,
    ),
    "instagram": PlatformSpec(
        platform="instagram",
        label="Instagram",
        caption_max=2200,
        accepts=["image", "video"],
        hashtag_suggestion=8,
    ),
    "facebook": PlatformSpec(
        platform="facebook",
        label="Facebook",
        caption_max=63206,
        accepts=["image", "video"],
        hashtag_suggestion=5,
    ),
    "tiktok": PlatformSpec(
        platform="tiktok",
        label="TikTok",
        caption_max=2200,
        title_max=150,
        # The adapter rejects anything but video (publishers/tiktok.py).
        accepts=["video"],
        hashtag_suggestion=5,
    ),
    "youtube": PlatformSpec(
        platform="youtube",
        label="YouTube",
        caption_max=5000,
        title_max=100,
        accepts=["video"],
        hashtag_suggestion=3,
    ),
}

# Bridges a real platform to the closest key in llm.SOCIAL_PLATFORMS, which is
# what the caption generator understands.
_LLM_PLATFORM = {
    "tiktok": "tiktok",
    "youtube": "youtube_shorts",
    "instagram": "instagram_reels",
    "facebook": "facebook_reels",
    # No LinkedIn or X entry exists there; Instagram's limits are the closest
    # long-caption profile, and the result is clamped by SPECS afterwards.
    "linkedin": "instagram_reels",
    "x": "tiktok",
}


def spec_for(platform: str) -> Optional[PlatformSpec]:
    return SPECS.get(platform)


def llm_platform_for(platform: str) -> str:
    return _LLM_PLATFORM.get(platform, "tiktok")


def all_specs() -> list[PlatformSpec]:
    return [SPECS[key] for key in sorted(SPECS)]
