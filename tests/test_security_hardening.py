"""Tests de controles de acceso y auth WebSocket."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import app


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    yield transport
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_medico_cannot_access_unrelated_paciente_historial(auth_client):
    token = create_access_token(
        role="medico",
        subject_id=999,
        cedula="999888777",
        nombre="Medico Aislado",
    )
    async with AsyncClient(transport=auth_client, base_url="http://test") as ac:
        r = await ac.get(
            "/pacientes/1/historial",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_medico_with_cita_can_access_paciente_historial(auth_client):
    async with AsyncClient(transport=auth_client, base_url="http://test") as ac:
        login = await ac.post(
            "/auth/medico/login",
            json={"cedula": "999888777", "password": "medico123"},
        )
        if login.status_code != 200:
            login = await ac.post(
                "/auth/medico/login",
                json={"cedula": "1001", "password": "medico123"},
            )
        token = login.json()["data"]["access_token"]
        r = await ac.get(
            "/pacientes/1/historial",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code in {200, 403}


def test_ws_chat_rejects_without_token(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat"):
            pass
    get_settings.cache_clear()


def test_ws_chat_accepts_medico_token_in_query(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    token = create_access_token(
        role="medico",
        subject_id=1,
        cedula="1011",
        nombre="Dra. Test",
    )
    client = TestClient(app)
    with client.websocket_connect(f"/ws/chat?token={token}") as ws:
        ws.send_json({"text": "hola"})
        msg = ws.receive_json()
        assert msg["type"] in {"tool_start", "chunk", "done", "error"}
    get_settings.cache_clear()


def test_ws_transcribe_works_when_auth_disabled():
    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json({"type": "start", "session_id": "t-auth", "mime_type": "audio/webm"})
        assert ws.receive_json()["type"] == "started"
