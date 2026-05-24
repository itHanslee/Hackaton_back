"""Reintentos para llamadas síncronas a Gemini (503/429/overloaded)."""

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_TRANSIENT_MARKERS = (
    "503",
    "429",
    "500",
    "502",
    "504",
    "unavailable",
    "overloaded",
    "resource exhausted",
    "rate limit",
    "deadline",
    "timeout",
    "internal error",
)

_QUOTA_MARKERS = (
    "quota exceeded",
    "exceeded your current quota",
    "resource_exhausted",
    "free_tier",
    "generate_content_free_tier",
)

_MIME_MARKERS = (
    "mime",
    "content type",
    "unsupported",
    "invalid argument",
    "could not process",
    "not supported",
)

_RETRY_DELAY_RE = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)\s*s", re.I)


def is_quota_exhausted_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _QUOTA_MARKERS)


def is_transient_gemini_error(exc: Exception) -> bool:
    if is_quota_exhausted_error(exc):
        return False
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def is_mime_gemini_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _MIME_MARKERS)


def _retry_delay_sec(exc: Exception, attempt: int, base_delay_sec: float) -> float:
    match = _RETRY_DELAY_RE.search(str(exc))
    if match:
        return max(float(match.group(1)), base_delay_sec)
    return base_delay_sec * (2 ** (attempt - 1))


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_sec: float = 1.0,
    label: str = "Gemini",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if is_quota_exhausted_error(exc):
                raise
            if attempt >= max_attempts or not is_transient_gemini_error(exc):
                raise
            delay = _retry_delay_sec(exc, attempt, base_delay_sec)
            logger.warning(
                "%s falló (intento %s/%s): %s — reintento en %.1fs",
                label,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
