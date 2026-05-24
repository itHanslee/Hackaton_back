"""Completions de texto/JSON con Google Gemini."""

from typing import TYPE_CHECKING

from app.services.gemini_retry import call_with_retry

if TYPE_CHECKING:
    from app.core.config import Settings

_SYSTEM = "Asistente médico MediNote. Respuestas concisas en español (Colombia)."


def complete_with_gemini(
    prompt: str,
    settings: "Settings",
    *,
    json_mode: bool = False,
) -> str:
    api_key = (settings.google_api_key or "").strip()
    if not api_key:
        raise ValueError("GOOGLE_API_KEY no configurada.")

    model = (settings.gemini_model or "gemini-2.0-flash").strip()

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ValueError(
            "Falta google-genai. Ejecuta: pip install google-genai"
        ) from exc

    client = genai.Client(api_key=api_key)
    config_kwargs: dict = {"temperature": 0.2}
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"

    def _call():
        response = client.models.generate_content(
            model=model,
            contents=f"{_SYSTEM}\n\n{prompt}",
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ValueError("Gemini devolvió una respuesta vacía.")
        return text

    return call_with_retry(_call, label="Gemini LLM")
