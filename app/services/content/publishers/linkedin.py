import requests

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    post_json,
    raise_for_response,
    register_adapter,
)

_REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_SOCIAL_ACTIONS_URL = "https://api.linkedin.com/v2/socialActions"
_SHARE_STATISTICS_URL = "https://api.linkedin.com/v2/organizationalEntityShareStatistics"


class LinkedInAdapter(PublisherAdapter):
    platform = "linkedin"
    supports_insights = True

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

    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        author_urn = credentials["author_urn"]
        share_urn = publication.platform_post_id
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        social_actions = get_json(f"{_SOCIAL_ACTIONS_URL}/{share_urn}", headers=headers)
        statistics = get_json(
            _SHARE_STATISTICS_URL,
            params={
                "q": "organizationalEntity",
                "organizationalEntity": author_urn,
                "shares[0]": share_urn,
            },
            headers=headers,
        )
        stats_row = (
            statistics.get("results", {}).get(share_urn, {}).get("totalShareStatistics", {})
        )

        return InsightsResult(
            # LinkedIn's post-level API has no unique-reach metric —
            # impressionCount is the volume figure it publishes, which is
            # why reach stays None and this platform gets substituted.
            impressions=stats_row.get("impressionCount"),
            likes=social_actions.get("likesSummary", {}).get("totalLikes"),
            comments=social_actions.get("commentsSummary", {}).get(
                "aggregatedTotalComments"
            ),
            shares=stats_row.get("shareCount"),
            raw={"social_actions": social_actions, "statistics": statistics},
        )


register_adapter(LinkedInAdapter())
