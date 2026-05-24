import re
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.security import decode_access_token

_PUBLIC_EXACT = {
    ("GET", "/health"),
    ("POST", "/auth/paciente/login"),
    ("POST", "/auth/medico/login"),
    ("POST", "/citas"),
    ("POST", "/pacientes"),
    ("GET", "/medicos"),
    ("GET", "/eps"),
    ("POST", "/transcribe"),
    ("POST", "/transcribe/json"),
}

_MEDICO_SLOTS = re.compile(r"^/medicos/\d+/slots$")
_EPS_LOGO = re.compile(r"^/eps/\d+/logo$")

_MEDICO_PREFIXES = [
    "/chat",
    "/consultas",
    "/historiales",
    "/medicamentos",
    "/ws/transcribe",
    "/medicos/me",
    "/eps/",
]

_PACIENTE_ME_PATHS = {
    "/pacientes/me/historial",
    "/pacientes/me/citas",
}

_PACIENTE_OWN_HISTORIAL = re.compile(r"^/pacientes/(\d+)/historial$")


def _unauthorized(message: str = "Token requerido.") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"data": None, "error": {"code": "UNAUTHORIZED", "message": message}},
    )


def _forbidden(message: str = "No tiene permiso para este recurso.") -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"data": None, "error": {"code": "FORBIDDEN", "message": message}},
    )


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


def _is_public(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    if (method, path) in _PUBLIC_EXACT:
        return True
    if method == "GET" and _MEDICO_SLOTS.match(path):
        return True
    if method == "GET" and _EPS_LOGO.match(path):
        return True
    return False


def _requires_medico(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _MEDICO_PREFIXES)


def _authorize(method: str, path: str, claims: dict[str, Any]) -> bool:
    role = claims.get("role")
    subject_id = claims.get("subject_id")

    if role == "paciente":
        if path in _PACIENTE_ME_PATHS and method == "GET":
            return True
        match = _PACIENTE_OWN_HISTORIAL.match(path)
        if match and method == "GET":
            return str(subject_id) == match.group(1)
        if path.startswith("/historiales/") and path.endswith("/pdf") and method == "GET":
            return True
        return False

    if role == "medico":
        if _requires_medico(path):
            return True
        match = _PACIENTE_OWN_HISTORIAL.match(path)
        if match and method == "GET":
            return True
        return False

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if settings.auth_disabled:
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path

        if _is_public(method, path):
            return await call_next(request)

        token = _extract_token(request)
        if not token:
            return _unauthorized()

        try:
            claims = decode_access_token(token)
        except Exception:
            return _unauthorized("Token inválido o expirado.")

        if not _authorize(method, path, claims):
            return _forbidden()

        request.state.auth = claims
        return await call_next(request)
