"""Autenticación JWT para WebSockets (AuthMiddleware no aplica a WS)."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketClose

from app.core.config import get_settings
from app.core.security import decode_access_token


async def require_ws_claims(
    websocket: WebSocket,
    *,
    roles: set[str] | None = None,
) -> dict[str, Any] | None:
    """
    Valida token JWT en query ?token= o header Authorization.
    Retorna claims o None si auth_disabled.
    Cierra el socket con 4401/4403 si auth requerida y falla.
    """
    settings = get_settings()
    if settings.auth_disabled:
        return {"role": "medico", "subject_id": 0, "sub": "dev"}

    token = websocket.query_params.get("token")
    if not token:
        auth = websocket.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if not token:
        await websocket.close(code=4401, reason="Token requerido")
        return None

    try:
        claims = decode_access_token(token)
    except Exception:
        await websocket.close(code=4401, reason="Token inválido")
        return None

    if roles and claims.get("role") not in roles:
        await websocket.close(code=4403, reason="Rol no autorizado")
        return None

    return claims
