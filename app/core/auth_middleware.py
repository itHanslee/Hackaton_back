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
    ("GET", "/medicos"),
    ("GET", "/eps"),
}

_UI_PREFIXES = ("/dev-ui",)

_MEDICO_SLOTS = re.compile(r"^/medicos/\d+/slots$")
_EPS_LOGO = re.compile(r"^/eps/\d+/logo$")
_PACIENTE_DETAIL = re.compile(r"^/pacientes/(\d+)$")
_PACIENTE_HISTORIAL_PDF = re.compile(r"^/pacientes/(\d+)/historial-pdf$")
_CITA_DETAIL = re.compile(r"^/citas/(\d+)$")

_MEDICO_PREFIXES = [
    "/chat",
    "/consultas",
    "/historiales",
    "/radicado",
    "/medicamentos",
    "/ws/chat",
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


def _is_ui_public(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _UI_PREFIXES)


def _is_public(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    if (method, path) in _PUBLIC_EXACT:
        return True
    if _is_ui_public(path):
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

    if role == "medico":
        if _requires_medico(path):
            return True
        if method == "GET" and path == "/pacientes":
            return True
        if method == "GET" and _PACIENTE_DETAIL.match(path):
            return True
        if method == "GET" and _PACIENTE_HISTORIAL_PDF.match(path):
            return True
        if method == "GET" and _PACIENTE_OWN_HISTORIAL.match(path):
            return True
        if method == "GET" and path.startswith("/citas/calendario"):
            return True
        if method == "GET" and _CITA_DETAIL.match(path):
            return True
        if method == "POST" and path == "/citas":
            return True
        if method in {"POST", "GET"} and path.startswith("/transcribe"):
            return True
        return False

    if role == "paciente":
        if path in _PACIENTE_ME_PATHS and method == "GET":
            return True
        detail_match = _PACIENTE_DETAIL.match(path)
        if detail_match and method == "GET":
            return str(subject_id) == detail_match.group(1)
        pdf_match = _PACIENTE_HISTORIAL_PDF.match(path)
        if pdf_match and method == "GET":
            return str(subject_id) == pdf_match.group(1)
        match = _PACIENTE_OWN_HISTORIAL.match(path)
        if match and method == "GET":
            return str(subject_id) == match.group(1)
        if path.startswith("/historiales/") and path.endswith("/pdf") and method == "GET":
            return True
        if method == "POST" and path == "/citas":
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
