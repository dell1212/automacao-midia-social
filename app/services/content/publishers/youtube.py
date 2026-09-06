import json

import requests

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    raise_for_response,
    register_adapter,
)

_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=multipart&part=snippet,status"
)
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeAdapter(PublisherAdapter):
    platform = "youtube"
    supports_insights = True

    def check_compatibility(self, piece, asset) -> None:
        if piece.type != ContentPieceType.video:
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "YouTube only accepts video pieces",
            )

    def publish(self, piece, asset, account, credentials, caption="") -> PublishResult:
        access_token = credentials["access_token"]
        video_bytes = get_bytes(asset.url)

        metadata = {
            "snippet": {
                # YouTube needs a separate short title; the caption is the body.
                "title": (caption or f"Content piece {piece.id}").splitlines()[0][:100],
                "description": caption,
            },
            "status": {"privacyStatus": "public"},
        }
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "video": (f"piece-{piece.id}.mp4", video_bytes, "video/mp4"),
        }

        try:
            response = requests.post(
                _UPLOAD_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                files=files,
                timeout=(10, 300),
            )
        except requests.RequestException as exc:
            raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
        raise_for_response(response)

        video_id = response.json()["id"]
        return PublishResult(
            platform_post_id=video_id,
            platform_post_url=f"https://www.youtube.com/watch?v={video_id}",
        )

    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        video_id = publication.platform_post_id

        response = get_json(
            _VIDEOS_URL,
            params={"part": "statistics", "id": video_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        items = response.get("items") or []
        if not items:
            raise PublicationError(
                PublicationErrorCode.invalid_params,
                f"YouTube returned no video for id {video_id}",
            )
        statistics = items[0]["statistics"]

        return InsightsResult(
            # No share count and no unique-reach metric in the YouTube Data
            # API v3 — viewCount is the only volume figure it publishes.
            # Every count field comes back as a string, a real quirk of this
            # API, hence the int() casts.
            impressions=int(statistics["viewCount"]) if "viewCount" in statistics else None,
            likes=int(statistics["likeCount"]) if "likeCount" in statistics else None,
            comments=(
                int(statistics["commentCount"]) if "commentCount" in statistics else None
            ),
            raw=response,
        )


register_adapter(YouTubeAdapter())
