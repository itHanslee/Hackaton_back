"""Transcripción de audio con Google Gemini (audio directo, sin ffmpeg)."""

import logging
from typing import TYPE_CHECKING

from app.services.gemini_retry import call_with_retry, is_mime_gemini_error

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

_TRANSCRIBE_PROMPT = """Transcribe este audio de una consulta médica en español (Colombia).
Devuelve ÚNICAMENTE la transcripción literal de lo que se dice.
Corrige puntuación y términos médicos obvios, pero no inventes síntomas, diagnósticos ni medicamentos.
Si no hay habla audible, responde exactamente: [sin audio]."""


def _normalize_mime(mime_type: str) -> str:
    mime = (mime_type or "audio/webm").lower().split(";")[0].strip()
    aliases = {
        "audio/wave": "audio/wav",
        "audio/x-wav": "audio/wav",
        "audio/mp3": "audio/mpeg",
        "audio/x-m4a": "audio/mp4",
    }
    return aliases.get(mime, mime)


def _gemini_mime(mime_type: str) -> str:
    """El navegador envía audio/webm; Gemini lo acepta directamente."""
    return _normalize_mime(mime_type)


def _fallback_mime(mime_type: str) -> str | None:
    normalized = _normalize_mime(mime_type)
    if normalized == "audio/webm":
        return "video/webm"
    return None


def _generate_transcription(client, model: str, data: bytes, mime_type: str):
    from google.genai import types

    contents = [
        types.Part.from_bytes(data=data, mime_type=mime_type),
        types.Part.from_text(text=_TRANSCRIBE_PROMPT),
    ]
    return client.models.generate_content(model=model, contents=contents)


def transcribe_with_gemini(data: bytes, mime_type: str, settings: "Settings") -> str:
    api_key = (settings.google_api_key or "").strip()
    if not api_key:
        raise ValueError("GOOGLE_API_KEY no configurada.")

    model = (settings.gemini_model or "gemini-2.0-flash").strip()

    try:
        from google import genai
    except ImportError as exc:
        raise ValueError(
            "Falta google-genai. Ejecuta: pip install google-genai"
        ) from exc

    client = genai.Client(api_key=api_key)
    gemini_mime = _gemini_mime(mime_type)

    try:
        response = call_with_retry(
            lambda: _generate_transcription(client, model, data, gemini_mime),
            label="Gemini STT",
        )
    except Exception as exc:
        alt_mime = _fallback_mime(mime_type)
        if not alt_mime or not is_mime_gemini_error(exc):
            raise ValueError(f"Gemini no pudo transcribir el audio: {exc}") from exc
        logger.warning("Reintentando transcripción Gemini con mime %s", alt_mime)
        try:
            response = call_with_retry(
                lambda: _generate_transcription(client, model, data, alt_mime),
                label="Gemini STT (mime alternativo)",
            )
        except Exception as retry_exc:
            raise ValueError(f"Gemini no pudo transcribir el audio: {retry_exc}") from retry_exc

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise ValueError("Gemini devolvió una transcripción vacía.")
    if text == "[sin audio]":
        raise ValueError("No se detectó habla en el audio.")
    return text
