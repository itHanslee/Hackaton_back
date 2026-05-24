from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.services.ai import AIService


@pytest.mark.asyncio
async def test_llm_complete_uses_gemini():
    settings = Settings(
        MOCK_AI=False,
        GOOGLE_API_KEY="google-key",
        GEMINI_MODEL="gemini-test",
    )
    ai = AIService(settings=settings)

    with patch(
        "app.services.ai.complete_with_gemini",
        return_value='{"motivo_consulta":"test"}',
    ) as mock_gemini:
        result = await ai._llm_complete("prompt", json_mode=True)

    assert result == '{"motivo_consulta":"test"}'
    mock_gemini.assert_called_once()
