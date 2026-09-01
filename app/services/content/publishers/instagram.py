import time

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_json,
    post_form,
    register_adapter,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
# Meta's own guidance: poll a container's status about once a minute, for up
# to 5 minutes, before giving up — https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/
_STATUS_POLL_INTERVAL_SECONDS = 60.0
_STATUS_POLL_TIMEOUT_SECONDS = 300.0


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

        self._wait_for_container(container_id, access_token)

        publish_response = post_form(
            f"{_GRAPH_API_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        media_id = publish_response.json()["id"]

        return PublishResult(
            platform_post_id=media_id,
            platform_post_url=f"https://www.instagram.com/p/{media_id}/",
        )

    def _wait_for_container(self, container_id: str, access_token: str) -> None:
        # Instagram processes media asynchronously — publishing a container
        # that isn't FINISHED yet can be rejected by the API. This blocks
        # until the container is actually ready, or fails clearly instead of
        # letting media_publish gamble on a race.
        deadline = time.monotonic() + _STATUS_POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            status = get_json(
                f"{_GRAPH_API_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
            )["status_code"]
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise PublicationError(
                    PublicationErrorCode.invalid_params,
                    f"Instagram container ended in status {status}",
                )
            time.sleep(_STATUS_POLL_INTERVAL_SECONDS)
        raise PublicationError(
            PublicationErrorCode.transient,
            "Instagram container did not finish processing in time",
        )


register_adapter(InstagramAdapter())
