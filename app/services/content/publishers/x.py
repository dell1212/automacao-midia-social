from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    post_form,
    post_json,
    register_adapter,
)

_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
_TWEETS_URL = "https://api.twitter.com/2/tweets"


class XAdapter(PublisherAdapter):
    platform = "x"
    supports_insights = True

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "X only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials, caption="") -> PublishResult:
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
            {"text": caption, "media": {"media_ids": [media_id]}},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        tweet_id = tweet_response.json()["data"]["id"]

        return PublishResult(
            platform_post_id=tweet_id,
            platform_post_url=f"https://x.com/i/web/status/{tweet_id}",
        )

    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        tweet_id = publication.platform_post_id

        response = get_json(
            f"{_TWEETS_URL}/{tweet_id}",
            params={"tweet.fields": "public_metrics"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        metrics = response["data"]["public_metrics"]
        retweets = metrics.get("retweet_count")
        quotes = metrics.get("quote_count")
        # X counts retweets and quote-tweets separately; both are a share of
        # the original post, so this adapter reports their sum. None only
        # when the API returns neither field at all.
        shares = None if retweets is None and quotes is None else (retweets or 0) + (quotes or 0)

        return InsightsResult(
            # X's public API has no unique-reach metric — impression_count is
            # the volume figure, which is why reach stays None here.
            impressions=metrics.get("impression_count"),
            likes=metrics.get("like_count"),
            comments=metrics.get("reply_count"),
            shares=shares,
            raw=response,
        )


register_adapter(XAdapter())
