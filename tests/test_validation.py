import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_chat_empty_body_uses_envelope(client):
    r = await client.post("/chat", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"]


@pytest.mark.asyncio
async def test_chat_slot_suggested_cardiologia(client):
    r = await client.post(
        "/chat",
        json={"text": "Quiero agendar una cita con el cardiologo manana"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["detected_intent"] == "agendar_cita"
    assert body["data"]["slot_suggested"] == "cardiologia"
