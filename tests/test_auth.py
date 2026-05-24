import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture
async def auth_client(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()
    os.environ["AUTH_DISABLED"] = "true"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_medico_login(auth_client):
    r = await auth_client.post(
        "/auth/medico/login",
        json={"cedula": "1001", "password": "medico123"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["role"] == "medico"
    assert data["access_token"]


@pytest.mark.asyncio
async def test_paciente_login(auth_client):
    r = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "paciente"


@pytest.mark.asyncio
async def test_consulta_requires_medico_token(auth_client):
    r = await auth_client.post(
        "/consultas/procesar",
        data={"paciente_id": "1", "cita_id": "1", "transcript": "test"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_citas_requires_token(auth_client):
    from datetime import datetime, timedelta

    slot_time = (datetime.utcnow() + timedelta(days=5)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    r = await auth_client.post(
        "/citas",
        json={
            "paciente_id": 1,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Control",
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_paciente_me_historial(auth_client):
    login = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await auth_client.get("/pacientes/me/historial", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


@pytest.mark.asyncio
async def test_cita_invalid_paciente_returns_404(auth_client):
    from datetime import datetime, timedelta

    login = await auth_client.post(
        "/auth/medico/login",
        json={"cedula": "1001", "password": "medico123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    slot_time = (datetime.utcnow() + timedelta(days=6)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    r = await auth_client.post(
        "/citas",
        headers=headers,
        json={
            "paciente_id": 99999,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Control",
        },
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_paciente_historial_own_only(auth_client):
    login = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    paciente_id = login.json()["data"]["user_id"]

    ok_r = await auth_client.get(f"/pacientes/{paciente_id}/historial", headers=headers)
    assert ok_r.status_code == 200

    forbidden = await auth_client.get("/pacientes/99999/historial", headers=headers)
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_paciente_cannot_book_for_other(auth_client):
    from datetime import datetime, timedelta

    login = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    slot_time = (datetime.utcnow() + timedelta(days=7)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    r = await auth_client.post(
        "/citas",
        headers=headers,
        json={
            "paciente_id": 99999,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Control",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_medico_me_citas(auth_client):
    from datetime import datetime, timedelta

    login = await auth_client.post(
        "/auth/medico/login",
        json={"cedula": "1001", "password": "medico123"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    slot_time = (datetime.utcnow() + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    create = await auth_client.post(
        "/citas",
        headers=headers,
        json={
            "paciente_id": 1,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Control calendario",
        },
    )
    assert create.status_code == 200

    month = slot_time.strftime("%Y-%m")
    r = await auth_client.get(f"/medicos/me/citas?month={month}", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] >= 1
    assert any(c["motivo"] == "Control calendario" for c in data["items"])
    assert data["items"][0]["paciente_nombre"]


@pytest.mark.asyncio
async def test_medico_me_citas_forbidden_for_paciente(auth_client):
    login = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await auth_client.get("/medicos/me/citas", headers=headers)
    assert r.status_code == 403
