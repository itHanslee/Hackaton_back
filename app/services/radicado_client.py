"""Cliente HTTP al microservicio PDF a Radicado (remoto)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RadicadoServiceError(Exception):
    def __init__(self, message: str, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = (settings.radicado_service_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.radicado_service_url.rstrip("/")


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.is_success:
        return
    detail: Any
    try:
        detail = response.json()
    except Exception:
        detail = response.text
    raise RadicadoServiceError(
        f"{context} falló (HTTP {response.status_code})",
        status_code=response.status_code,
        detail=detail,
    )


def health_check(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    timeout = httpx.Timeout(10.0, connect=5.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.get(f"{_base_url(settings)}/health", headers=_headers(settings))
        _raise_for_status(response, "Health radicado")
        return response.json()


def ocr_pdf(pdf_bytes: bytes, filename: str = "incapacidad.pdf", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    timeout = httpx.Timeout(settings.radicado_timeout_sec, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{_base_url(settings)}/demo/ocr",
            headers=_headers(settings),
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
        _raise_for_status(response, "OCR")
        return response.json()


def validar_rethus(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    timeout = httpx.Timeout(settings.radicado_timeout_sec, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{_base_url(settings)}/demo/rethus",
            headers={**_headers(settings), "Content-Type": "application/json"},
            json=payload,
        )
        _raise_for_status(response, "RETHUS")
        return response.json()


def validar_adres(
    *,
    tipo_documento: str,
    numero_documento: str,
    eps_laravel: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    timeout = httpx.Timeout(settings.radicado_timeout_sec, connect=10.0)
    params = {
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "eps_laravel": eps_laravel,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{_base_url(settings)}/demo/adres/validar",
            headers=_headers(settings),
            params=params,
        )
        _raise_for_status(response, "ADRES")
        data = response.json()
        status = data.get("status")
        if status in {"manual_verification_required", "error"}:
            logger.info("ADRES requiere modo asistido: %s", status)
            assisted = client.post(
                f"{_base_url(settings)}/demo/adres/asistido",
                headers=_headers(settings),
                params={**params, "wait_seconds": 180},
            )
            _raise_for_status(assisted, "ADRES asistido")
            return assisted.json()
        return data
