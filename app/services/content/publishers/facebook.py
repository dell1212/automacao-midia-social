from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_form,
    register_adapter,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class FacebookAdapter(PublisherAdapter):
    platform = "facebook"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "Facebook only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        page_id = credentials["page_id"]
        endpoint = "videos" if piece.type == ContentPieceType.video else "photos"
        media_field = "file_url" if piece.type == ContentPieceType.video else "url"

        response = post_form(
            f"{_GRAPH_API_BASE}/{page_id}/{endpoint}",
            data={media_field: asset.url, "access_token": access_token},
        )
        post_id = response.json()["id"]

        return PublishResult(
            platform_post_id=post_id,
            platform_post_url=f"https://www.facebook.com/{post_id}",
        )


register_adapter(FacebookAdapter())
