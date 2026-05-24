import asyncio
import base64
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.audio import check_audio_size, decode_base64_audio
from app.core.config import Settings, get_settings
from app.models.schemas import HistorialClinico, IntentType, MedicamentoItem
from app.services.intents import classify_intent_rule_based, intent_reply_message

logger = logging.getLogger(__name__)

HISTORIAL_JSON_SCHEMA = """
{
  "motivo": "string",
  "sintomas": ["string"],
  "diagnostico": "string",
  "plan": "string",
  "medicamentos": [{"nombre": "string", "dosis": "string", "frecuencia": "string", "duracion": "string"}]
}
"""


class ServiceError(Exception):
    """Error de servicio con codigo estable para la API."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ProcessChatResult:
    intent: IntentType
    message: str | None
    historial: HistorialClinico | None


class AIService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate_api_keys(self) -> None:
        if self.settings.mock_ai:
            return
        if not (self.settings.azure_api_key or "").strip():
            raise ServiceError(
                "MISSING_AZURE_API_KEY",
                "AZURE_API_KEY es obligatoria para transcripcion con Grok STT.",
            )
        if self.settings.llm_provider == "anthropic":
            if not (self.settings.anthropic_api_key or "").strip():
                raise ServiceError(
                    "MISSING_ANTHROPIC_KEY",
                    "ANTHROPIC_API_KEY es obligatoria con llm_provider=anthropic.",
                )

    def _ensure_api_keys(self) -> None:
        self.validate_api_keys()

    def _timeout_sec(self) -> float:
        return float(getattr(self.settings, "api_timeout_sec", 60.0))

    async def transcribe_audio_base64(self, audio_b64: str, mime_type: str) -> str:
        try:
            raw = decode_base64_audio(audio_b64)
        except ValueError as exc:
            raise ValueError(f"Audio invalido: {exc}") from exc

        check_audio_size(raw, max_mb=self.settings.max_audio_mb)

        if self.settings.mock_ai:
            return "Paciente refiere dolor de cabeza desde hace dos dias, sin fiebre."

        return await self.transcribe_bytes(raw, mime_type)

    async def transcribe_bytes(self, data: bytes, mime_type: str) -> str:
        if self.settings.mock_ai:
            return "Paciente refiere dolor de cabeza desde hace dos dias, sin fiebre."

        self._ensure_api_keys()
        check_audio_size(data, max_mb=self.settings.max_audio_mb)
        return await self._grok_transcribe_bytes(data, mime_type)

    async def _grok_transcribe_bytes(self, data: bytes, mime_type: str) -> str:
        self._ensure_api_keys()
        try:
            return await asyncio.wait_for(
                self._grok_transcribe_bytes_impl(data, mime_type),
                timeout=self._timeout_sec(),
            )
        except asyncio.TimeoutError as exc:
            raise ServiceError(
                "STT_TIMEOUT",
                f"La transcripcion supero {self._timeout_sec():.0f}s.",
            ) from exc

    async def _grok_transcribe_bytes_impl(self, data: bytes, mime_type: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.settings.azure_api_key,
            base_url=self.settings.azure_ai_stt_endpoint,
        )
        audio_b64 = base64.b64encode(data).decode("ascii")
        prompt = (
            "Transcribe exactamente este audio medico en espanol. "
            "Devuelve solo la transcripcion limpia, sin explicaciones."
        )
        response = await client.chat.completions.create(
            model=self.settings.stt_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n"
                        f"MIME: {mime_type}\n"
                        f"AUDIO_BASE64:\n{audio_b64}"
                    ),
                }
            ],
        )
        return (response.choices[0].message.content or "").strip()

    async def resolve_intent(self, text: str, *, generate_historial: bool = False, classify_intent: bool | None = None) -> IntentType:
        if generate_historial:
            return "generar_historial"
        if classify_intent is False:
            return "desconocido"
        return await self.classify_intent(text)

    async def process_chat(
        self,
        text: str,
        *,
        generate_historial: bool = False,
        classify_intent: bool | None = None,
        include_chat_reply: bool | None = None,
        context: dict[str, str] | None = None,
    ) -> ProcessChatResult:
        if classify_intent is None:
            classify_intent = not generate_historial
        if include_chat_reply is None:
            include_chat_reply = not generate_historial

        if generate_historial:
            intent: IntentType = "generar_historial"
        elif classify_intent:
            intent = await self.classify_intent(text)
        else:
            intent = "desconocido"

        historial: HistorialClinico | None = None
        if generate_historial or intent == "generar_historial":
            historial = await self.generate_historial(text, context=context)

        message: str | None = None
        if include_chat_reply:
            message = await self.chat_reply(text, intent)

        return ProcessChatResult(intent=intent, message=message, historial=historial)

    async def classify_intent(self, text: str) -> IntentType:
        if self.settings.mock_ai:
            return classify_intent_rule_based(text)

        self._ensure_api_keys()
        prompt = (
            "Clasifica la intencion del usuario en UNA de estas etiquetas exactas: "
            "agendar_cita, consulta_medica, generar_historial, desconocido.\n"
            f"Texto: {text}\n"
            "Responde solo con la etiqueta, sin explicacion."
        )
        label = (await self._llm_complete(prompt)).strip().lower()
        allowed: list[IntentType] = ["agendar_cita", "consulta_medica", "generar_historial", "desconocido"]
        if label in allowed:
            return label  # type: ignore[return-value]
        return classify_intent_rule_based(text)

    async def generate_historial(self, transcript: str, context: dict[str, str] | None = None) -> HistorialClinico:
        if self.settings.mock_ai:
            return _mock_historial_from_transcript(transcript, context)

        self._ensure_api_keys()
        prompt = _historial_prompt(transcript, context)
        raw = await self._llm_complete(prompt)
        try:
            return _parse_historial_json(raw)
        except ValueError:
            logger.warning("Historial JSON invalido, reintentando una vez")
            retry_prompt = prompt + "\n\nIMPORTANTE: Tu respuesta anterior no fue JSON valido. Responde UNICAMENTE con un objeto JSON que cumpla el esquema, sin markdown."
            raw_retry = await self._llm_complete(retry_prompt)
            return _parse_historial_json(raw_retry)

    async def chat_reply(self, text: str, intent: IntentType) -> str:
        if self.settings.mock_ai:
            return intent_reply_message(intent)

        self._ensure_api_keys()
        prompt = (
            "Eres MediNote, asistente medico en espanol (Colombia). "
            f"Intencion detectada: {intent}. "
            f"Mensaje del usuario: {text}\n"
            "Responde en 1-2 frases, claro y profesional."
        )
        return await self._llm_complete(prompt)

    async def _llm_complete(self, user_prompt: str) -> str:
        self._ensure_api_keys()
        try:
            if self.settings.llm_provider == "anthropic":
                return await asyncio.wait_for(self._anthropic_complete(user_prompt), timeout=self._timeout_sec())
            return await asyncio.wait_for(self._openai_complete(user_prompt), timeout=self._timeout_sec())
        except asyncio.TimeoutError as exc:
            raise ServiceError("LLM_TIMEOUT", f"El modelo supero {self._timeout_sec():.0f}s.") from exc

    async def _openai_complete(self, user_prompt: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        response = await client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": "Asistente medico MediNote. Respuestas concisas en espanol."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip()

    async def _anthropic_complete(self, user_prompt: str) -> str:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        response = await client.messages.create(
            model=self.settings.llm_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts = [b.text for b in response.content if hasattr(b, "text")]
        return "".join(parts).strip()


def _historial_prompt(transcript: str, context: dict[str, str] | None) -> str:
    ctx_block = ""
    if context:
        lines = "\n".join(f"- {k}: {v}" for k, v in context.items())
        ctx_block = f"\nContexto adicional:\n{lines}\n"
    return f"""Eres un asistente medico. A partir de la transcripcion de una consulta en espanol (Colombia),
genera un historial clinico en JSON valido con este esquema exacto:
{HISTORIAL_JSON_SCHEMA}

Reglas:
- No inventes datos que no aparezcan en la transcripcion; usa valores conservadores si falta informacion.
- Responde SOLO con el JSON, sin markdown ni texto adicional.
{ctx_block}
Transcripcion:
{transcript}
"""


def _mock_historial_from_transcript(transcript: str, context: dict[str, str] | None = None) -> HistorialClinico:
    t = transcript.strip()
    lower = t.lower()
    ctx = context or {}

    sintomas: list[str] = []
    if "dolor" in lower:
        sintomas.append("Dolor referido por el paciente")
    if "fiebre" in lower:
        sintomas.append("Fiebre")
    if not sintomas:
        sintomas = ["Sintomas descritos en consulta"]

    motivo = ctx.get("motivo") or _derive_motivo(t, lower)
    diagnostico = ctx.get("diagnostico") or _derive_diagnostico(lower, motivo)
    plan = ctx.get("plan") or "Seguimiento ambulatorio; control si empeoran los sintomas."

    return HistorialClinico(motivo=motivo, sintomas=sintomas, diagnostico=diagnostico, plan=plan, medicamentos=[])


def _derive_motivo(transcript: str, lower: str) -> str:
    if "dolor de cabeza" in lower or "cefalea" in lower:
        return "Cefalea"
    first = transcript.split(".")[0].strip()
    return first or "Motivo de consulta"


def _derive_diagnostico(lower: str, motivo: str) -> str:
    if "cefalea" in lower or "dolor de cabeza" in lower:
        return "Cefalea tensional (R51)"
    return f"Impresion diagnostica acorde a: {motivo}"


def _parse_historial_json(raw: str) -> HistorialClinico:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
        return HistorialClinico.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid historial JSON from LLM: %s", exc)
        raise ValueError("El modelo no devolvio un historial JSON valido") from exc
