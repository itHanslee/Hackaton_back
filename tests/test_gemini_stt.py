from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.services.ai import AIService


@pytest.mark.asyncio
async def test_transcribe_bytes_uses_gemini():
    settings = Settings(
        MOCK_AI=False,
        GOOGLE_API_KEY="test-key",
        GEMINI_MODEL="gemini-test",
    )
    ai = AIService(settings=settings)

    with patch(
        "app.services.ai.transcribe_with_gemini",
        return_value="Paciente refiere cefalea.",
    ) as mock_gemini:
        result = await ai.transcribe_bytes(b"fake-audio", "audio/webm")

    assert result == "Paciente refiere cefalea."
    mock_gemini.assert_called_once()


@pytest.mark.asyncio
async def test_transcribe_bytes_mock_skips_gemini():
    settings = Settings(MOCK_AI=True, GOOGLE_API_KEY="test-key")
    ai = AIService(settings=settings)

    with patch("app.services.ai.transcribe_with_gemini") as mock_gemini:
        result = await ai.transcribe_bytes(b"fake-audio", "audio/webm")

    assert "Paciente refiere" in result
    mock_gemini.assert_not_called()
