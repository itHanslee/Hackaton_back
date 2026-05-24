import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
async def auth_client(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()


async def _medico_headers(client: AsyncClient) -> dict:
    login = await client.post(
        "/auth/medico/login",
        json={"cedula": "1001", "password": "medico123"},
    )
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_firma_requires_auth(auth_client):
    files = {"file": ("firma.png", io.BytesIO(PNG_1X1), "image/png")}
    r = await auth_client.post("/medicos/me/firma", files=files)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_medico_upload_and_get_firma(auth_client):
    headers = await _medico_headers(auth_client)
    files = {"file": ("firma.png", io.BytesIO(PNG_1X1), "image/png")}
    upload = await auth_client.post("/medicos/me/firma", headers=headers, files=files)
    assert upload.status_code == 200
    assert upload.json()["data"]["firma_url"] == "/medicos/me/firma"

    profile = await auth_client.get("/medicos/me", headers=headers)
    assert profile.json()["data"]["tiene_firma"] is True

    get_firma = await auth_client.get("/medicos/me/firma", headers=headers)
    assert get_firma.status_code == 200
    assert "image" in get_firma.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_paciente_cannot_upload_firma(auth_client):
    login = await auth_client.post(
        "/auth/paciente/login",
        json={"cedula": "2001", "password": "paciente123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    files = {"file": ("firma.png", io.BytesIO(PNG_1X1), "image/png")}
    r = await auth_client.post("/medicos/me/firma", headers=headers, files=files)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_medico_upload_eps_logo_own_eps(auth_client):
    headers = await _medico_headers(auth_client)
    profile = await auth_client.get("/medicos/me", headers=headers)
    eps_id = profile.json()["data"]["eps_id"]

    files = {"file": ("logo.png", io.BytesIO(PNG_1X1), "image/png")}
    upload = await auth_client.post(f"/eps/{eps_id}/logo", headers=headers, files=files)
    assert upload.status_code == 200

    logo = await auth_client.get(f"/eps/{eps_id}/logo")
    assert logo.status_code == 200


@pytest.mark.asyncio
async def test_medico_cannot_upload_other_eps_logo(auth_client):
    headers = await _medico_headers(auth_client)
    profile = await auth_client.get("/medicos/me", headers=headers)
    eps_id = profile.json()["data"]["eps_id"]
    other_eps = 999 if eps_id != 999 else 998

    files = {"file": ("logo.png", io.BytesIO(PNG_1X1), "image/png")}
    r = await auth_client.post(f"/eps/{other_eps}/logo", headers=headers, files=files)
    assert r.status_code in (403, 404)
