import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "ok"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_chat_text_agendar(client):
    r = await client.post("/chat", json={"text": "Quiero agendar una cita con el cardiólogo"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["data"]["detected_intent"] == "agendar_cita"
    assert body["data"]["message"]


@pytest.mark.asyncio
async def test_chat_generar_historial(client):
    r = await client.post(
        "/chat",
        json={
            "text": "Paciente con dolor de cabeza dos días, sin fiebre. Paracetamol indicado.",
            "generate_historial": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["historial"] is not None
    assert "motivo_consulta" in body["data"]["historial"]
    assert body["data"]["historial"]["alergias"] == "No definido"


@pytest.mark.asyncio
async def test_historiales_generate(client):
    r = await client.post(
        "/historiales/generate",
        json={"transcript": "Consulta por dolor abdominal. Diagnóstico: gastritis."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["historial"]["diagnostico"]


@pytest.mark.asyncio
async def test_chat_validation_empty(client):
    r = await client.post("/chat", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_historiales_generate_returns_id(client):
    r = await client.post(
        "/historiales/generate",
        json={"transcript": "Paciente con tos y fiebre."},
    )
    assert r.status_code == 200
    assert "historial_id" in r.json()["data"]
