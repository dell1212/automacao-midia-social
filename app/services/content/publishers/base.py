import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

from app.models.content import ContentSocialAccount, ContentPiece
from app.models.content_generation import ContentAsset
from app.services.content.crypto import decrypt_credentials
from app.services.content.publish_errors import (
    PublicationError,
    PublicationErrorCode,
    classify_http_status,
)

_POLICY_KEYWORDS = (
    "policy",
    "content violat",
    "community guideline",
    "not allowed",
    "prohibited",
)


@dataclass(frozen=True)
class PublishResult:
    platform_post_id: str
    platform_post_url: str


class PublisherAdapter(ABC):
    platform: str

    @abstractmethod
    def check_compatibility(self, piece: ContentPiece, asset: ContentAsset) -> None:
        ...

    @abstractmethod
    def publish(
        self,
        piece: ContentPiece,
        asset: ContentAsset,
        account: ContentSocialAccount,
        credentials: dict,
    ) -> PublishResult:
        ...


_ADAPTER_REGISTRY: dict[str, PublisherAdapter] = {}


def register_adapter(adapter: PublisherAdapter) -> None:
    _ADAPTER_REGISTRY[adapter.platform] = adapter


def get_adapter(platform: str) -> PublisherAdapter:
    adapter = _ADAPTER_REGISTRY.get(platform)
    if adapter is None:
        raise PublicationError(
            PublicationErrorCode.unsupported_capability,
            f"No publisher adapter registered for platform '{platform}'",
        )
    return adapter


def load_credentials(account: ContentSocialAccount) -> dict:
    return json.loads(decrypt_credentials(account.credentials_encrypted))


def _extract_error_message(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message", data))
        return str(data.get("message", data))
    return str(data)


def _looks_like_content_policy_rejection(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in _POLICY_KEYWORDS)


def raise_for_response(response) -> None:
    if response.status_code < 400:
        return
    message = _extract_error_message(response)
    code = (
        PublicationErrorCode.content_policy
        if _looks_like_content_policy_rejection(message)
        else classify_http_status(response.status_code)
    )
    raise PublicationError(code, message)


def post_form(url: str, data=None, *, headers=None, files=None, timeout=(10, 60)):
    try:
        response = requests.post(url, data=data, headers=headers, files=files, timeout=timeout)
    except requests.RequestException as exc:
        raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
    raise_for_response(response)
    return response


def post_json(url: str, json_body: dict, *, headers: dict, timeout=(10, 60)):
    try:
        response = requests.post(url, json=json_body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
    raise_for_response(response)
    return response


def get_bytes(url: str, *, timeout=(10, 120)) -> bytes:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PublicationError(
            PublicationErrorCode.transient, f"failed to fetch asset: {exc}"
        ) from exc
    return response.content
