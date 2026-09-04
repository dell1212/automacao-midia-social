import time

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_json,
    register_adapter,
)

_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
# Upload/processing on TikTok's side is usually done in tens of seconds, not
# minutes — much shorter budget than Instagram's, but still bounded.
_STATUS_POLL_INTERVAL_SECONDS = 5.0
_STATUS_POLL_TIMEOUT_SECONDS = 300.0
_TERMINAL_NON_PUBLISHED_STATUSES = ("FAILED", "SEND_TO_USER_INBOX")


class TikTokAdapter(PublisherAdapter):
    platform = "tiktok"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type != ContentPieceType.video:
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "TikTok only accepts video pieces",
            )

    def publish(self, piece, asset, account, credentials, caption="") -> PublishResult:
        access_token = credentials["access_token"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        response = post_json(
            _INIT_URL,
            {
                "post_info": {
                    "title": (caption or f"Content piece {piece.id}").splitlines()[0][:150],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": asset.url},
            },
            headers=headers,
        )
        publish_id = response.json()["data"]["publish_id"]

        post_id = self._wait_for_publish(publish_id, headers)

        # TikTok's status API returns only a post id, never a public URL —
        # building one would need the creator's username, which isn't part
        # of this response and isn't worth a second API call to guess at.
        return PublishResult(platform_post_id=post_id, platform_post_url=None)

    def _wait_for_publish(self, publish_id: str, headers: dict) -> str:
        # `publish_id` is just an upload-tracking token — the real post id
        # (and whether the post actually went public) only exists once
        # TikTok finishes processing, which this polls for.
        deadline = time.monotonic() + _STATUS_POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            data = post_json(
                _STATUS_URL, {"publish_id": publish_id}, headers=headers
            ).json()["data"]
            status = data.get("status")
            if status == "PUBLISH_COMPLETE":
                return str(data["publicaly_available_post_id"][0])
            if status in _TERMINAL_NON_PUBLISHED_STATUSES:
                reason = data.get("fail_reason", status)
                raise PublicationError(
                    PublicationErrorCode.invalid_params,
                    f"TikTok publish ended in status {status}: {reason}",
                )
            time.sleep(_STATUS_POLL_INTERVAL_SECONDS)
        raise PublicationError(
            PublicationErrorCode.transient,
            "TikTok publish did not finish processing in time",
        )


register_adapter(TikTokAdapter())
