"""Orquestación de tools del agente conversacional."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.services.chat_agent.tools import (
    buscar_medico_tool,
    consulta_medica_tool,
    crear_cita_tool,
    crear_paciente_tool,
    generar_historial_tool,
    monitor_paciente_tool,
)


async def execute_tool(
    tool_name: str,
    text: str,
    extra_payload: dict[str, Any] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    extra_payload = extra_payload or {}
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        if tool_name == "crear_paciente":
            return await crear_paciente_tool(db, text, extra_payload)
        if tool_name == "monitor_paciente":
            return await monitor_paciente_tool(db, text, extra_payload)
        if tool_name == "generar_historial":
            return await generar_historial_tool(db, text, extra_payload)
        if tool_name == "buscar_medico":
            return await buscar_medico_tool(db, text, extra_payload)
        if tool_name == "crear_cita":
            return await crear_cita_tool(db, text, extra_payload)
        return await consulta_medica_tool(text)
    finally:
        if own_session and db is not None:
            db.close()


class ChatAgentService:
    """Fachada para ejecutar tools con sesión opcional de BD."""

    def __init__(self, db: Session | None = None):
        self._db = db

    async def execute_tool(
        self,
        tool_name: str,
        text: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await execute_tool(tool_name, text, extra_payload, db=self._db)
