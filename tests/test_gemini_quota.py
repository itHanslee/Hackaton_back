"""Tests de manejo de cuota Gemini."""

import pytest

from app.core.config import Settings
from app.services.ai import AIService, ServiceError
from app.services.gemini_retry import call_with_retry, is_quota_exhausted_error


def test_is_quota_exhausted_error():
    exc = Exception(
        "429 RESOURCE_EXHAUSTED quota exceeded for generate_content_free_tier_requests"
    )
    assert is_quota_exhausted_error(exc) is True
    assert is_quota_exhausted_error(Exception("503 unavailable")) is False


def test_call_with_retry_does_not_retry_quota():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise Exception("429 quota exceeded free_tier")

    with pytest.raises(Exception):
        call_with_retry(fn, max_attempts=3)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_generate_historial_fallback_on_quota():
    settings = Settings(
        MOCK_AI=False,
        GOOGLE_API_KEY="google-key",
        GEMINI_FALLBACK_ON_QUOTA=True,
    )
    ai = AIService(settings=settings)

    async def _raise_quota(*_args, **_kwargs):
        raise ServiceError("GEMINI_QUOTA_EXCEEDED", "Cuota agotada")

    ai._llm_complete = _raise_quota  # type: ignore[method-assign]

    historial = await ai.generate_historial(
        "Paciente con dolor de cabeza dos días, paracetamol indicado."
    )
    assert historial.motivo_consulta
    assert historial.sintomas
