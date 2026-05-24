"""WebSocket session buffer for live transcription."""

import asyncio
import base64
import logging
from dataclasses import dataclass, field

from app.core.audio import AudioValidationError, check_audio_size, decode_base64_audio
from app.core.config import Settings, get_settings
from app.core.responses import safe_client_message
from app.services.ai import AIService

logger = logging.getLogger(__name__)

MOCK_PARTIAL_TEXT = "Paciente refiere molestias durante la consulta."


@dataclass
class TranscriptionSession:
    session_id: str
    buffer_chunks: list[bytes] = field(default_factory=list)
    full_transcript: str = ""
    mime_type: str = "audio/webm"
    total_bytes: int = 0
    chunk_count: int = 0

    def append_chunk(self, audio_b64: str, settings: Settings) -> None:
        if self.chunk_count >= settings.max_ws_chunks:
            raise AudioValidationError(
                f"Se superó el límite de {settings.max_ws_chunks} fragmentos por sesión."
            )

        raw = decode_base64_audio(audio_b64, validate=True)

        max_session_bytes = settings.max_audio_mb * 1024 * 1024
        if self.total_bytes + len(raw) > max_session_bytes:
            raise AudioValidationError(
                f"El audio de la sesión supera el límite de {settings.max_audio_mb} MB."
            )

        self.buffer_chunks.append(raw)
        self.total_bytes += len(raw)
        self.chunk_count += 1

    def flush_buffer(self) -> bytes:
        data = b"".join(self.buffer_chunks)
        self.buffer_chunks.clear()
        return data


class TranscriptionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TranscriptionSession] = {}
        self._ai = AIService()
        self._settings = get_settings()

    def start_session(self, session_id: str, mime_type: str = "audio/webm") -> TranscriptionSession:
        session = TranscriptionSession(session_id=session_id, mime_type=mime_type)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> TranscriptionSession | None:
        return self._sessions.get(session_id)

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @staticmethod
    def ws_error_payload(exc: Exception, *, default_code: str = "TRANSCRIBE_FAILED") -> dict:
        if isinstance(exc, AudioValidationError):
            message = str(exc)
            lowered = message.lower()
            if "base64" in lowered:
                code = "INVALID_BASE64"
            elif "fragmentos" in lowered:
                code = "MAX_CHUNKS"
            elif "sesión" in lowered or "sesion" in lowered:
                code = "SESSION_TOO_LARGE"
            elif "supera" in lowered or "límite" in lowered or "limite" in lowered:
                code = "AUDIO_TOO_LARGE"
            else:
                code = "AUDIO_INVALID"
            return {
                "type": "error",
                "code": code,
                "message": safe_client_message(message, fallback="Audio inválido."),
            }
        return {
            "type": "error",
            "code": default_code,
            "message": safe_client_message(
                None,
                fallback="No se pudo transcribir el audio. Intente de nuevo.",
            ),
        }

    async def transcribe_buffer(self, session: TranscriptionSession) -> str:
        data = session.flush_buffer()
        if not data:
            return ""

        check_audio_size(data)

        try:
            if hasattr(self._ai, "transcribe_bytes"):
                text = await self._ai.transcribe_bytes(data, session.mime_type)
            else:
                audio_b64 = base64.b64encode(data).decode("ascii")
                text = await self._ai.transcribe_audio_base64(audio_b64, session.mime_type)
        except AudioValidationError:
            raise
        except Exception:
            logger.exception("Transcribe buffer failed for session %s", session.session_id)
            raise AudioValidationError(
                "No se pudo transcribir el audio."
            ) from None

        session.full_transcript = f"{session.full_transcript} {text}".strip()
        return text

    async def periodic_transcribe_loop(
        self,
        session_id: str,
        send_callback,
        stop_event: asyncio.Event,
    ) -> None:
        """Optional mock partials while recording; real transcription runs on stop."""
        if not self._settings.ws_transcribe_on_interval:
            await stop_event.wait()
            return

        interval = self._settings.ws_transcribe_interval_sec
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                session = self.get_session(session_id)
                if not session or not session.buffer_chunks:
                    continue
                if not self._settings.mock_ai:
                    continue
                try:
                    await send_callback({"type": "partial", "text": MOCK_PARTIAL_TEXT})
                except Exception:
                    logger.exception("Periodic partial send failed")
                    await send_callback(
                        self.ws_error_payload(
                            Exception("partial"),
                            default_code="TRANSCRIBE_FAILED",
                        )
                    )
