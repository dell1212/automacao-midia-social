import random
import time
from typing import Callable, Optional, TypeVar

from loguru import logger

from app.services.content.errors import GenerationError, is_retryable

T = TypeVar("T")

# Tuned for paid provider endpoints: a short burst of retries absorbs rate
# limits and blips without keeping a worker thread parked for minutes. Not
# tenant-configurable in this phase — see the spec's Retry Policy section.
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SECONDS = 30.0
JITTER_RATIO = 0.25


def backoff_delay(attempt: int, *, random_fn: Callable[[], float] = random.random) -> float:
    """Exponential backoff with jitter. `attempt` is 1-based."""
    raw = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** max(attempt - 1, 0))
    capped = min(raw, MAX_BACKOFF_SECONDS)
    return capped * (1 + JITTER_RATIO * random_fn())


def run_with_retry(
    operation: Callable[[], T],
    *,
    on_attempt: Optional[Callable[[int], None]] = None,
) -> T:
    """Run `operation`, retrying only errors classified as retryable.

    Raises the last GenerationError when attempts run out, so the caller can
    decide whether to fall back to the next provider candidate.
    """
    last_error: Optional[GenerationError] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return operation()
        except GenerationError as error:
            last_error = error
            if not is_retryable(error.code):
                raise
            if attempt == MAX_ATTEMPTS:
                break
            delay = backoff_delay(attempt)
            logger.warning(
                f"generation attempt {attempt}/{MAX_ATTEMPTS} failed "
                f"({error.code.value}), retrying in {delay:.1f}s"
            )
            time.sleep(delay)

    raise last_error
