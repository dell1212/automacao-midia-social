from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_json,
    register_adapter,
)

_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"


class TikTokAdapter(PublisherAdapter):
    platform = "tiktok"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type != ContentPieceType.video:
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "TikTok only accepts video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        response = post_json(
            _INIT_URL,
            {
                "post_info": {
                    "title": (piece.generation_prompt or f"Content piece {piece.id}")[:150],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": asset.url},
            },
            headers=headers,
        )
        publish_id = response.json()["data"]["publish_id"]

        return PublishResult(
            platform_post_id=publish_id,
            platform_post_url=f"https://www.tiktok.com/publish/status/{publish_id}",
        )


register_adapter(TikTokAdapter())
