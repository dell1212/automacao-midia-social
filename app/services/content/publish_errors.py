from enum import Enum


class PublicationErrorCode(str, Enum):
    rate_limit = "rate_limit"
    transient = "transient"
    invalid_credentials = "invalid_credentials"
    invalid_params = "invalid_params"
    content_policy = "content_policy"
    unsupported_capability = "unsupported_capability"


# Only the moment-dependent failures are worth retrying — a bad token or a
# rejected upload fails identically on every attempt.
RETRYABLE_ERROR_CODES = frozenset(
    {PublicationErrorCode.rate_limit, PublicationErrorCode.transient}
)


class PublicationError(Exception):
    """An adapter call failed, classified into the canonical publish taxonomy."""

    def __init__(self, code: PublicationErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_retryable(code: PublicationErrorCode) -> bool:
    return code in RETRYABLE_ERROR_CODES


def classify_http_status(status_code: int) -> PublicationErrorCode:
    if status_code == 429:
        return PublicationErrorCode.rate_limit
    if status_code >= 500:
        return PublicationErrorCode.transient
    if status_code in (401, 403):
        return PublicationErrorCode.invalid_credentials
    if status_code in (400, 404, 422):
        return PublicationErrorCode.invalid_params
    return PublicationErrorCode.invalid_params
