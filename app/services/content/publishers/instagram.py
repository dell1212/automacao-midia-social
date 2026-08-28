from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_form,
    register_adapter,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramAdapter(PublisherAdapter):
    platform = "instagram"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "Instagram only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        ig_user_id = credentials["ig_user_id"]

        media_field = "video_url" if piece.type == ContentPieceType.video else "image_url"
        container_payload = {media_field: asset.url, "access_token": access_token}
        if piece.type == ContentPieceType.video:
            container_payload["media_type"] = "REELS"

        container_response = post_form(
            f"{_GRAPH_API_BASE}/{ig_user_id}/media", data=container_payload
        )
        container_id = container_response.json()["id"]

        publish_response = post_form(
            f"{_GRAPH_API_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        media_id = publish_response.json()["id"]

        return PublishResult(
            platform_post_id=media_id,
            platform_post_url=f"https://www.instagram.com/p/{media_id}/",
        )


register_adapter(InstagramAdapter())
