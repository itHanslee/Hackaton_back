from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    data: Any | None = None
    error: ErrorDetail | None = None


def ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}


_UNSAFE_PATTERNS = (
    "traceback",
    "exception",
    "error at",
    "file \"",
    "line ",
    ".py",
    "stack",
    "internal server",
)


def safe_client_message(
    detail: str | None = None,
    *,
    fallback: str = "Ha ocurrido un error.",
) -> str:
    """Return a short client-safe message without leaking internals."""
    if detail is None:
        return fallback

    text = str(detail).strip()
    if not text or len(text) > 400:
        return fallback

    lowered = text.lower()
    if any(pattern in lowered for pattern in _UNSAFE_PATTERNS):
        return fallback

    return text


def error_response(code: str, message: str, status_code: int = 400):
    from fastapi.responses import JSONResponse

    safe_message = safe_client_message(message, fallback="Ha ocurrido un error.")
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": safe_message}},
    )
