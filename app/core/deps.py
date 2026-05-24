from typing import Any

from fastapi import Request

from app.core.security import decode_access_token


def get_auth_claims(request: Request) -> dict[str, Any] | None:
    claims = getattr(request.state, "auth", None)
    if claims:
        return claims

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return decode_access_token(auth[7:].strip())
    except Exception:
        return None


def require_medico(request: Request) -> tuple[dict[str, Any], int] | None:
    """Returns (claims, medico_id) or None if not authorized as medico."""
    claims = get_auth_claims(request)
    if not claims or claims.get("role") != "medico":
        return None
    subject_id = claims.get("subject_id")
    if subject_id is None:
        return None
    return claims, int(subject_id)
