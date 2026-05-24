import re

from app.models.schemas import IntentType

_AGENDAR = re.compile(
    r"\b(cita|agendar|agenda|turno|disponibilidad|horario|médico|medico|doctor)\b",
    re.I,
)
_CONSULTA = re.compile(
    r"\b(consulta|síntoma|sintoma|dolor|diagnóstico|diagnostico|examen|historia)\b",
    re.I,
)
_HISTORIAL = re.compile(
    r"\b(historial|resumen|informe|cerrar consulta|generar historial|firmar)\b",
    re.I,
)

_SLOT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(card[ií]olog|coraz[oó]n|card[ií]ac)\w*\b", re.I), "cardiologia"),
    (re.compile(r"\b(pediatr|niñ[oa]s?|infantil)\w*\b", re.I), "pediatria"),
    (re.compile(r"\b(dermatolog|piel|cut[aá]ne)\w*\b", re.I), "dermatologia"),
    (re.compile(r"\b(ginecolog|obstetr|embaraz)\w*\b", re.I), "ginecologia"),
    (re.compile(r"\b(traumatolog|ortoped|fractur|hueso)\w*\b", re.I), "traumatologia"),
    (re.compile(r"\b(neurolog|migrañ|convulsi)\w*\b", re.I), "neurologia"),
]


def classify_intent_rule_based(text: str) -> IntentType:
    """Fast fallback when MOCK_AI or LLM unavailable."""
    if _HISTORIAL.search(text):
        return "generar_historial"
    if _AGENDAR.search(text):
        return "agendar_cita"
    if _CONSULTA.search(text):
        return "consulta_medica"
    return "desconocido"


def suggest_slot(intent: IntentType, text: str) -> str | None:
    """Especialidad sugerida al agendar cita (p. ej. cardiologia)."""
    if intent != "agendar_cita":
        return None
    for pattern, slot in _SLOT_HINTS:
        if pattern.search(text):
            return slot
    return None


def intent_reply_message(intent: IntentType) -> str:
    messages = {
        "agendar_cita": "Entendido, quieres agendar una cita. Te mostraré los horarios disponibles.",
        "consulta_medica": "Iniciemos la consulta. Puedes hablar o escribir los síntomas del paciente.",
        "generar_historial": "Voy a generar el historial clínico con la información de la consulta.",
        "desconocido": "No estoy seguro de lo que necesitas. ¿Quieres agendar una cita o iniciar una consulta?",
    }
    return messages[intent]
