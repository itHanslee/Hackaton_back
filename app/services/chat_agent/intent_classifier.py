"""Clasificación de intents unificada (REST + WebSocket agent)."""

from app.services.intents import classify_intent_rule_based, suggest_slot

_AGENT_MONITOR = ("monitorear paciente", "monitor paciente", "estado del paciente", "seguimiento paciente")
_AGENT_CREATE_PATIENT = ("crear paciente", "registrar paciente", "nuevo paciente", "alta paciente")


def classify_intent(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in _AGENT_MONITOR):
        return "monitor_paciente"
    if any(w in lower for w in _AGENT_CREATE_PATIENT):
        return "crear_paciente"

    base = classify_intent_rule_based(text)
    if base == "generar_historial":
        return "generar_historial"
    if base == "agendar_cita":
        return "agendar_cita"
    if base == "consulta_medica":
        return "consulta_medica"
    return "consulta_medica"


def suggested_specialty(text: str) -> str | None:
    return suggest_slot("agendar_cita", text)
