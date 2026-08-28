from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_bytes,
    post_form,
    post_json,
    register_adapter,
)

_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
_TWEETS_URL = "https://api.twitter.com/2/tweets"


class XAdapter(PublisherAdapter):
    platform = "x"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "X only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        media_bytes = get_bytes(asset.url)
        media_category = (
            "tweet_video" if piece.type == ContentPieceType.video else "tweet_image"
        )

        upload_response = post_form(
            _UPLOAD_URL,
            data={"media_category": media_category},
            headers={"Authorization": f"Bearer {access_token}"},
            files={"media": media_bytes},
        )
        media_id = upload_response.json()["media_id_string"]

        tweet_response = post_json(
            _TWEETS_URL,
            {"text": piece.generation_prompt or "", "media": {"media_ids": [media_id]}},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        tweet_id = tweet_response.json()["data"]["id"]

        return PublishResult(
            platform_post_id=tweet_id,
            platform_post_url=f"https://x.com/i/web/status/{tweet_id}",
        )


register_adapter(XAdapter())
