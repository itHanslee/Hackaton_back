"""Tests de radicación de incapacidades (cliente mockeado)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


def _unique_slot(day_offset: int, hour: int, minute: int) -> datetime:
    return (datetime.utcnow() + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


@pytest.fixture
async def medico_client(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
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
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac
    get_settings.cache_clear()


def _mock_remote():
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with (
            patch(
                "app.services.radicado_pipeline.ocr_pdf",
                return_value={"extracted_data": {"paciente_nombre": "Test", "registro_medico": "999888777"}},
            ),
            patch(
                "app.services.radicado_pipeline.validar_rethus",
                return_value={"status": "success", "medico": {"rethus": "VALIDADO", "nombre": "Dr Test"}},
            ),
            patch(
                "app.services.radicado_pipeline.validar_adres",
                return_value={
                    "status": "success",
                    "eps_encontrada": "Sura",
                    "estado_afiliacion": "ACTIVO",
                    "coincide_con_eps_laravel": True,
                },
            ),
        ):
            yield

    return _ctx()


@pytest.mark.asyncio
async def test_generar_documento_incapacidad(medico_client):
    slot = _unique_slot(day_offset=40, hour=14, minute=0)
    cita = await medico_client.post(
        "/citas",
        json={"paciente_id": 1, "medico_id": 1, "fecha_hora": slot.isoformat(), "motivo": "Control"},
    )
    assert cita.status_code == 200

    proc = await medico_client.post(
        "/consultas/procesar",
        data={"paciente_id": "1", "cita_id": str(cita.json()["data"]["id"]), "transcript": "Dolor generalizado"},
    )
    assert proc.status_code == 200
    historial_id = proc.json()["data"]["historial_id"]

    confirm = await medico_client.put(
        f"/historiales/{historial_id}",
        json={
            "motivo_consulta": "Control",
            "sintomas": ["fiebre"],
            "diagnostico": "J06.9 infección respiratoria",
            "plan_tratamiento": "Reposo",
            "medicamentos": {},
            "confirmado_por_medico": True,
            "requiere_incapacidad": True,
            "incapacidad_dias": 5,
        },
    )
    assert confirm.status_code == 200

    doc = await medico_client.post(
        f"/radicado/historiales/{historial_id}/documento",
        json={"incapacidad_dias": 5},
    )
    assert doc.status_code == 200
    assert doc.json()["data"]["metadata"]["paciente_nombre"]


@pytest.mark.asyncio
async def test_iniciar_radicacion_mocked(medico_client):
    slot = _unique_slot(day_offset=41, hour=14, minute=30)
    cita = await medico_client.post(
        "/citas",
        json={"paciente_id": 1, "medico_id": 1, "fecha_hora": slot.isoformat(), "motivo": "Control"},
    )
    assert cita.status_code == 200, cita.text
    proc = await medico_client.post(
        "/consultas/procesar",
        data={"paciente_id": "1", "cita_id": str(cita.json()["data"]["id"]), "transcript": "Reposo médico"},
    )
    historial_id = proc.json()["data"]["historial_id"]
    await medico_client.put(
        f"/historiales/{historial_id}",
        json={
            "motivo_consulta": "Control",
            "sintomas": ["malestar"],
            "diagnostico": "M79.3 mialgia",
            "plan_tratamiento": "Reposo",
            "medicamentos": {},
            "confirmado_por_medico": True,
            "requiere_incapacidad": True,
            "incapacidad_dias": 3,
        },
    )
    await medico_client.post(f"/radicado/historiales/{historial_id}/documento", json={})

    import asyncio

    with _mock_remote():
        start = await medico_client.post("/radicado/incapacidades", json={"historial_id": historial_id})
        assert start.status_code == 200
        job_id = start.json()["data"]["job_id"]
        assert job_id

        data = None
        status = None
        for _ in range(50):
            await asyncio.sleep(0.3)
            status = await medico_client.get(f"/radicado/incapacidades/{job_id}")
            data = status.json()["data"]
            if data["estado"] in {"completo", "error"}:
                break

    assert status.status_code == 200
    assert data["estado"] == "completo"
    assert data["pasos"]["reporte"] is not None
    assert data["score"] is not None


def test_build_validation_report():
    from app.services.radicado_report import build_validation_report

    report = build_validation_report(
        {
            "numero_incapacidad": "INC-1",
            "fecha_inicio": "2026-01-01",
            "fecha_fin": "2026-01-05",
            "dias": 5,
            "diagnostico_codigo": "J06.9",
            "paciente_nombre": "Carlos",
            "paciente_numero_documento": "111",
            "eps_detectada": "Sura",
            "medico_nombre": "Ana",
            "registro_medico": "999",
        },
        {"status": "success", "medico": {"rethus": "VALIDADO", "nombre": "Ana"}},
        {
            "status": "success",
            "eps_encontrada": "Sura",
            "estado_afiliacion": "ACTIVO",
            "coincide_con_eps_laravel": True,
        },
    )
    assert report["score_global"] == 100
    assert report["status"] == "COMPLETO Y VERIFICADO"
