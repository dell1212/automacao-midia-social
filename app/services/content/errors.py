from enum import Enum


class GenerationErrorCode(str, Enum):
    rate_limit = "rate_limit"
    transient = "transient"
    timeout = "timeout"
    invalid_credentials = "invalid_credentials"
    invalid_params = "invalid_params"
    content_policy = "content_policy"
    unsupported_capability = "unsupported_capability"
    no_compatible_model = "no_compatible_model"
    unknown = "unknown"


# Retrying only helps when the failure is about the moment, not the request.
# A bad credential or a rejected prompt fails identically on every attempt, so
# retrying it just burns time and, on paid endpoints, money.
RETRYABLE_ERROR_CODES = frozenset(
    {
        GenerationErrorCode.rate_limit,
        GenerationErrorCode.transient,
        GenerationErrorCode.timeout,
    }
)


class GenerationError(Exception):
    """A provider call failed, classified into the canonical taxonomy."""

    def __init__(self, code: GenerationErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_retryable(code: GenerationErrorCode) -> bool:
    return code in RETRYABLE_ERROR_CODES


def classify_http_status(status_code: int) -> GenerationErrorCode:
    if status_code == 429:
        return GenerationErrorCode.rate_limit
    if status_code >= 500:
        return GenerationErrorCode.transient
    if status_code in (401, 403):
        return GenerationErrorCode.invalid_credentials
    if status_code in (400, 404, 422):
        return GenerationErrorCode.invalid_params
    return GenerationErrorCode.unknown
