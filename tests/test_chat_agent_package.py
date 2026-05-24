"""Tests del paquete chat_agent (iteración 2)."""

from datetime import datetime

import pytest

from app.services.chat_agent import (
    INTENT_TO_TOOL,
    TOOLS,
    ChatAgentService,
    classify_intent,
    suggested_specialty,
)
from app.services.chat_agent.helpers import extract_date_from_text, list_slots_for_agent, resolve_slot_datetime
from app.services.job_runner import submit_background


def test_classify_intent_unified_with_intents_module():
    assert classify_intent("Quiero agendar una cita con el cardiólogo") == "agendar_cita"
    assert classify_intent("Generar historial de la consulta") == "generar_historial"
    assert classify_intent("Monitorear paciente 111000111") == "monitor_paciente"
    assert classify_intent("Registrar paciente nuevo") == "crear_paciente"
    assert classify_intent("Tengo dolor de cabeza") == "consulta_medica"


def test_suggested_specialty():
    assert suggested_specialty("cita con cardiologo") == "cardiologia"
    assert suggested_specialty("agendar turno") is None


def test_intent_to_tool_consulta_medica():
    assert INTENT_TO_TOOL["consulta_medica"] == "consulta_medica"
    assert INTENT_TO_TOOL["agendar_cita"] == "buscar_medico"
    assert "crear_paciente" in TOOLS


def test_extract_date_from_text():
    assert extract_date_from_text("cita para mañana") is not None
    assert extract_date_from_text("2026-06-01") == "2026-06-01"


def test_list_slots_uses_slots_service():
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        slots = list_slots_for_agent(db, medico_id=1)
        assert isinstance(slots, list)
        if slots:
            assert "id" in slots[0]
            assert "datetime" in slots[0]
    finally:
        db.close()


def test_resolve_slot_datetime():
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        slots = list_slots_for_agent(db, medico_id=1)
        if not slots:
            pytest.skip("No hay slots disponibles en seed")
        slot_id = slots[0]["id"]
        resolved = resolve_slot_datetime(db, medico_id=1, slot_id=slot_id)
        assert isinstance(resolved, datetime)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_chat_agent_service_execute_consulta():
    svc = ChatAgentService()
    result = await svc.execute_tool("consulta_medica", "Hola, tengo una duda")
    assert "success" in result


def test_job_runner_submits():
    done = []

    def task(x):
        done.append(x)

    future = submit_background(task, 42)
    future.result(timeout=5)
    assert done == [42]
