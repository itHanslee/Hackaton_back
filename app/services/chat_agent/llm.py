"""Respuestas Azure OpenAI y selección de tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AzureOpenAI

from app.core.config import Settings, get_settings
from app.services.chat_agent.constants import INTENT_TO_TOOL, SYSTEM_PROMPT, TOOL_SELECTION_PROMPT, TOOLS

logger = logging.getLogger(__name__)


def fallback_reply(intent: str, result: dict[str, Any], tool_name: str, text: str) -> str:
    if tool_name == "monitor_paciente" and result.get("patient"):
        p = result["patient"]
        alerts = result.get("alerts") or []
        lines = [
            f"Monitoreo de **{p.get('nombre', 'Paciente')}**",
            f"- Documento: {p.get('documento') or 'No definido'}",
            f"- EPS: {p.get('eps') or 'No definido'}",
            f"- Consultas registradas: {p.get('total_consultas', 0)}",
        ]
        if alerts:
            lines.append("- Alertas: " + " | ".join(alerts))
        return "\n".join(lines)
    if tool_name == "crear_paciente" and result.get("patient"):
        p = result["patient"]
        status = "creado" if result.get("created") else "ya existia"
        return (
            f"Paciente {status}: **{p.get('nombre', 'Paciente')}**\n\n"
            f"- ID: `{p.get('id', '')}`\n"
            f"- Documento: {p.get('documento') or 'No definido'}\n"
            f"- EPS: {p.get('eps') or 'No definido'}"
        )
    if tool_name == "generar_historial" and result.get("historial"):
        return "He generado el historial clinico basado en la consulta."
    if tool_name == "buscar_medico" and result.get("medicos"):
        medicos = result["medicos"]
        slots = result.get("slots", [])[:5]
        lines = [f"Encontre **{len(medicos)} medico(s) disponible(s)**:\n"]
        for m in medicos:
            lines.append(f"- **{m['nombre']}** — {m['especialidad']}")
        if slots:
            horas = ", ".join(s["hora"] for s in slots)
            lines.append(f"\n**Horarios disponibles hoy:** {horas}")
        lines.append("\nDime cual prefieres y te ayudo a agendar la cita.")
        return "\n".join(lines)
    if tool_name == "crear_cita" and result.get("cita"):
        c = result["cita"]
        pac = c.get("paciente", {})
        return (
            f"Cita confirmada (ID: `{c['id']}`)\n\n"
            f"- **Paciente:** {pac.get('nombre', '—')}\n"
            f"- **EPS:** {pac.get('eps', '—')}\n"
            f"- **Medico:** {c['medico']} ({c['especialidad']})\n"
            f"- **Fecha:** {c['fecha']} a las {c['hora']}\n"
        )
    msg = result.get("message", "").strip()
    if msg:
        return msg
    if intent == "agendar_cita":
        return "Te ayudo a agendar. Dime especialidad y fecha preferida."
    if intent == "generar_historial":
        return "Voy a generar el historial clinico con la informacion disponible."
    return f"Entendido. Recibi tu mensaje: {text[:180]}"


def _azure_client(settings: Settings) -> AzureOpenAI | None:
    if not settings.azure_api_key:
        return None
    return AzureOpenAI(
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_api_key,
    )


def generate_reply(
    intent: str,
    user_text: str,
    tool_name: str,
    tool_result: dict[str, Any],
    conversation_history: list[dict[str, str]] | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    client = _azure_client(settings)
    if client is None:
        return fallback_reply(intent, tool_result, tool_name, user_text)
    try:
        history_snippet = "[]"
        if conversation_history:
            try:
                history_snippet = json.dumps(conversation_history[-12:], ensure_ascii=False)
            except Exception:
                history_snippet = "[]"
        completion = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            max_completion_tokens=1200,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Historial reciente: {history_snippet}\n"
                        f"Usuario: {user_text}\n"
                        f"Intent: {intent}\n"
                        f"Tool: {tool_name}\n"
                        f"Resultado tool: {json.dumps(tool_result, ensure_ascii=False)}\n"
                        "Genera la respuesta final para el usuario."
                    ),
                },
            ],
        )
        content = (completion.choices[0].message.content or "").strip()
        return content or fallback_reply(intent, tool_result, tool_name, user_text)
    except Exception as exc:
        logger.warning("Azure OpenAI error: %s", exc)
        return fallback_reply(intent, tool_result, tool_name, user_text)


def choose_tool_with_ai(
    text: str,
    intent: str,
    history: list[dict[str, str]] | None = None,
    settings: Settings | None = None,
) -> str:
    default_tool = INTENT_TO_TOOL.get(intent, "consulta_medica")
    settings = settings or get_settings()
    client = _azure_client(settings)
    if client is None:
        return default_tool
    try:
        history_snippet = "[]"
        if history:
            history_snippet = json.dumps(history[-12:], ensure_ascii=False)
        completion = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            max_completion_tokens=120,
            messages=[
                {"role": "system", "content": TOOL_SELECTION_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Intent detectado: {intent}\n"
                        f"Mensaje usuario: {text}\n"
                        f"Historial reciente: {history_snippet}\n"
                        f"Tool por defecto: {default_tool}\n"
                        "Devuelve JSON con la tool elegida."
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        raw = (completion.choices[0].message.content or "").strip()
        parsed = json.loads(raw) if raw else {}
        selected = str(parsed.get("tool") or "").strip()
        if selected in TOOLS:
            return selected
    except Exception as exc:
        logger.warning("Tool selection AI fallback: %s", exc)
    return default_tool


def stream_reply(
    intent: str,
    user_text: str,
    tool_name: str,
    tool_result: dict[str, Any],
    conversation_history: list[dict[str, str]] | None = None,
    settings: Settings | None = None,
):
    """Generador sincrono — hace yield de cada token en tiempo real (stream=True)."""
    settings = settings or get_settings()
    client = _azure_client(settings)
    if client is None:
        yield fallback_reply(intent, tool_result, tool_name, user_text)
        return
    try:
        history_snippet = "[]"
        if conversation_history:
            try:
                history_snippet = json.dumps(conversation_history[-12:], ensure_ascii=False)
            except Exception:
                history_snippet = "[]"
        stream = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            max_completion_tokens=1200,
            stream=True,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Historial reciente: {history_snippet}\n"
                        f"Usuario: {user_text}\n"
                        f"Intent: {intent}\n"
                        f"Tool: {tool_name}\n"
                        f"Resultado tool: {json.dumps(tool_result, ensure_ascii=False)}\n"
                        "Genera la respuesta final para el usuario."
                    ),
                },
            ],
        )
        has_content = False
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                has_content = True
                yield delta.content
        if not has_content:
            yield fallback_reply(intent, tool_result, tool_name, user_text)
    except Exception as exc:
        logger.warning("Azure OpenAI stream error: %s", exc)
        yield fallback_reply(intent, tool_result, tool_name, user_text)
