import requests

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_bytes,
    post_json,
    raise_for_response,
    register_adapter,
)

_REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


class LinkedInAdapter(PublisherAdapter):
    platform = "linkedin"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "LinkedIn only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials, caption="") -> PublishResult:
        access_token = credentials["access_token"]
        author_urn = credentials["author_urn"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        recipe = (
            "urn:li:digitalmediaRecipe:feedshare-video"
            if piece.type == ContentPieceType.video
            else "urn:li:digitalmediaRecipe:feedshare-image"
        )

        register_response = post_json(
            _REGISTER_UPLOAD_URL,
            {
                "registerUploadRequest": {
                    "recipes": [recipe],
                    "owner": author_urn,
                    "serviceRelationships": [
                        {
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent",
                        }
                    ],
                }
            },
            headers=headers,
        )
        upload_data = register_response.json()["value"]
        upload_url = upload_data["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = upload_data["asset"]

        media_bytes = get_bytes(asset.url)
        try:
            upload_result = requests.put(
                upload_url,
                data=media_bytes,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(10, 300),
            )
        except requests.RequestException as exc:
            raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
        raise_for_response(upload_result)

        media_category = "VIDEO" if piece.type == ContentPieceType.video else "IMAGE"
        post_response = post_json(
            _UGC_POSTS_URL,
            {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": caption},
                        "shareMediaCategory": media_category,
                        "media": [{"status": "READY", "media": asset_urn}],
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            headers=headers,
        )
        post_id = post_response.headers.get("x-restli-id", asset_urn)

        return PublishResult(
            platform_post_id=post_id,
            platform_post_url=f"https://www.linkedin.com/feed/update/{post_id}/",
        )


register_adapter(LinkedInAdapter())
