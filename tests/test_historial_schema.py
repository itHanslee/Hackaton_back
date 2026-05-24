import json
from pathlib import Path

import pytest

from app.models.schemas import HistorialClinico

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "historial_sample.json"


def test_fixture_matches_historial_schema():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    historial = HistorialClinico.model_validate(data)
    assert historial.motivo
    assert historial.diagnostico
    assert isinstance(historial.sintomas, list)


@pytest.mark.asyncio
async def test_mock_historial_derives_from_transcript():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/historiales",
            json={"transcript": "Consulta por dolor abdominal. Diagnóstico: gastritis."},
        )
    assert r.status_code == 200
    historial = r.json()["data"]["historial"]
    combined = f"{historial['motivo']} {historial['diagnostico']}".lower()
    assert "gastritis" in combined or "abdominal" in combined
