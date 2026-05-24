from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_medicos(client):
    r = await client.get("/medicos")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert len(body["data"]) >= 1


@pytest.mark.asyncio
async def test_medico_slots(client):
    r = await client.get("/medicos/1/slots")
    assert r.status_code == 200
    slots = r.json()["data"]["slots"]
    assert len(slots) == 16
    assert "id" in slots[0]
    assert "datetime" in slots[0]


@pytest.mark.asyncio
async def test_create_cita(client):
    slot_time = (datetime.utcnow() + timedelta(days=2)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    r = await client.post(
        "/citas",
        json={
            "paciente_id": 1,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Control general",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["estado"] == "pendiente"


@pytest.mark.asyncio
async def test_medicamentos_by_diagnostico(client):
    r = await client.get("/medicamentos", params={"diagnostico": "Hipertensión", "eps_id": 1})
    assert r.status_code == 200
    body = r.json()["data"]
    assert "disponibles_eps" in body
    assert "ideales_sugeridos" in body
    assert len(body["disponibles_eps"]) >= 1


@pytest.mark.asyncio
async def test_paciente_historial_empty(client):
    r = await client.get("/pacientes/1/historial")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_e2e_consulta_and_historial(client):
    slot_time = (datetime.utcnow() + timedelta(days=3)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    cita_r = await client.post(
        "/citas",
        json={
            "paciente_id": 1,
            "medico_id": 1,
            "fecha_hora": slot_time.isoformat(),
            "motivo": "Consulta por cefalea",
        },
    )
    cita_id = cita_r.json()["data"]["id"]

    proc_r = await client.post(
        "/consultas/procesar",
        data={
            "paciente_id": "1",
            "cita_id": str(cita_id),
            "transcript": "Paciente refiere cefalea frontal de dos días, sin fiebre. "
            "Se indica acetaminofén 500 mg cada 8 horas.",
        },
    )
    assert proc_r.status_code == 200
    proc_body = proc_r.json()["data"]
    assert proc_body["transcripcion"]
    assert proc_body["historial"]["motivo_consulta"]
    assert "medicamentos" in proc_body["historial"]

    consulta_id = proc_body["consulta_id"]
    hist_r = await client.post(
        "/historiales",
        json={
            "consulta_id": consulta_id,
            "motivo_consulta": proc_body["historial"]["motivo_consulta"],
            "sintomas": proc_body["historial"]["sintomas"],
            "diagnostico": proc_body["historial"]["diagnostico"],
            "plan_tratamiento": proc_body["historial"]["plan_tratamiento"],
            "medicamentos": proc_body["historial"]["medicamentos"],
            "confirmado_por_medico": True,
        },
    )
    assert hist_r.status_code == 200
    historial_id = hist_r.json()["data"]["historial_id"]

    pdf_r = await client.get(f"/historiales/{historial_id}/pdf")
    assert pdf_r.status_code == 200
    assert pdf_r.headers["content-type"] == "application/pdf"
    assert pdf_r.content.startswith(b"%PDF")

    hist_list = await client.get("/pacientes/1/historial")
    assert len(hist_list.json()["data"]) >= 1
