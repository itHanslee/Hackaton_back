"""Transcripción de voz vía Groq Whisper (agente conversacional)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

_http_client: httpx.AsyncClient | None = None


async def init_http_client() -> None:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _client() -> httpx.AsyncClient:
    if _http_client is None:
        raise HTTPException(status_code=500, detail="HTTP client no inicializado")
    return _http_client


async def transcribe(
    audio_bytes: bytes,
    mime_type: str,
    *,
    language: str | None = "es",
    prompt: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY no configurada")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio vacio")

    ext = "webm"
    mime = mime_type.lower()
    if "ogg" in mime:
        ext = "ogg"
    elif "wav" in mime:
        ext = "wav"
    elif "mp3" in mime or "mpeg" in mime:
        ext = "mp3"
    elif "mp4" in mime or "m4a" in mime:
        ext = "m4a"
    elif "flac" in mime:
        ext = "flac"

    files = {"file": (f"audio.{ext}", audio_bytes, mime_type)}
    data: dict[str, str] = {
        "model": settings.groq_stt_model,
        "response_format": "json",
        "temperature": "0",
    }
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt

    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    try:
        resp = await _client().post(GROQ_STT_URL, headers=headers, files=files, data=data)
    except httpx.HTTPError as exc:
        logger.warning("Groq STT network error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error de red Groq: {exc}") from exc

    if resp.status_code >= 400:
        logger.warning("Groq STT %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(status_code=resp.status_code, detail=f"Groq STT: {resp.text[:200]}")

    try:
        payload = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Respuesta Groq invalida") from exc

    return {"transcript": (payload.get("text") or "").strip(), "raw": payload}
