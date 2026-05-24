"""Reintentos para llamadas síncronas a Gemini (503/429/overloaded)."""

import logging
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

_MIME_MARKERS = (
    "mime",
    "content type",
    "unsupported",
    "invalid argument",
    "could not process",
    "not supported",
)


def is_transient_gemini_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def is_mime_gemini_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _MIME_MARKERS)


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
            if attempt >= max_attempts or not is_transient_gemini_error(exc):
                raise
            delay = base_delay_sec * (2 ** (attempt - 1))
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
