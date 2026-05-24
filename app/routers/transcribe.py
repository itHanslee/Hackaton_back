import asyncio
import base64
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.audio import ALLOWED_MIME_TYPES, AudioValidationError
from app.core.config import get_settings
from app.core.responses import ok, safe_client_message
from app.services import groq_stt
from app.services.transcription import TranscriptionManager

router = APIRouter(tags=["transcribe"])
logger = logging.getLogger(__name__)
_settings = get_settings()
_transcription = TranscriptionManager()


class TranscribeJSONRequest(BaseModel):
    audio: str
    mime_type: str = "audio/webm"
    language: str | None = "es"
    prompt: str | None = None


@router.websocket("/ws/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """
    Transcripción en tiempo real.

    Cliente → {"type":"start","session_id":"...","mime_type":"audio/webm"}
    Cliente → {"type":"audio","chunk":"<base64>"}
    Cliente → {"type":"stop"}
    Servidor → {"type":"started"|"partial"|"final"|"error", ...}
    """
    await websocket.accept()
    session_id: str | None = None
    stop_event = asyncio.Event()
    loop_task: asyncio.Task | None = None

    async def send(msg: dict) -> None:
        await websocket.send_json(msg)

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "start":
                session_id = raw.get("session_id") or "default"
                mime = raw.get("mime_type", "audio/webm")
                if mime.lower() not in ALLOWED_MIME_TYPES:
                    await send(
                        {
                            "type": "error",
                            "code": "INVALID_MIME",
                            "message": "Tipo de audio no permitido.",
                        }
                    )
                    continue
                _transcription.start_session(session_id, mime)
                stop_event.clear()
                if loop_task and not loop_task.done():
                    loop_task.cancel()
                if _settings.ws_transcribe_on_interval:
                    loop_task = asyncio.create_task(
                        _transcription.periodic_transcribe_loop(session_id, send, stop_event)
                    )
                await send({"type": "started", "session_id": session_id})

            elif msg_type == "audio":
                if not session_id:
                    await send(
                        {"type": "error", "code": "NO_SESSION", "message": "Envíe start primero"}
                    )
                    continue
                chunk = raw.get("chunk")
                if not chunk:
                    await send({"type": "error", "code": "EMPTY_CHUNK", "message": "chunk vacío"})
                    continue
                session = _transcription.get_session(session_id)
                if not session:
                    await send(
                        {"type": "error", "code": "NO_SESSION", "message": "Sesión no encontrada"}
                    )
                    continue
                try:
                    session.append_chunk(chunk, _settings)
                except AudioValidationError as exc:
                    await send(_transcription.ws_error_payload(exc))

            elif msg_type == "stop":
                if not session_id:
                    await send({"type": "error", "code": "NO_SESSION", "message": "Sin sesión activa"})
                    continue
                stop_event.set()
                if loop_task and not loop_task.done():
                    loop_task.cancel()
                    try:
                        await loop_task
                    except asyncio.CancelledError:
                        pass
                session = _transcription.get_session(session_id)
                if session and session.buffer_chunks:
                    try:
                        await _transcription.transcribe_buffer(session)
                    except AudioValidationError as exc:
                        logger.warning("Final transcribe validation failed: %s", exc)
                        await send(_transcription.ws_error_payload(exc))
                    except Exception:
                        logger.exception("Final buffer transcribe failed")
                        await send(
                            _transcription.ws_error_payload(
                                Exception("transcribe"),
                                default_code="TRANSCRIBE_FAILED",
                            )
                        )
                final = session.full_transcript if session else ""
                await send({"type": "final", "text": final, "session_id": session_id})
                _transcription.end_session(session_id)
                session_id = None
                loop_task = None

            else:
                await send(
                    {
                        "type": "error",
                        "code": "UNKNOWN_TYPE",
                        "message": f"Tipo desconocido: {msg_type}",
                    }
                )

    except WebSocketDisconnect:
        if session_id:
            stop_event.set()
            if loop_task and not loop_task.done():
                loop_task.cancel()
            _transcription.end_session(session_id)
    except Exception:
        logger.exception("WebSocket error")
        try:
            await send(
                {
                    "type": "error",
                    "code": "INTERNAL",
                    "message": safe_client_message(
                        None,
                        fallback="Error interno del servidor.",
                    ),
                }
            )
        except Exception:
            pass
        await websocket.close()


@router.post("/transcribe")
async def transcribe_multipart(
    file: UploadFile | None = File(default=None),
    language: str | None = Form(default="es"),
    prompt: str | None = Form(default=None),
):
    """STT Groq — multipart (baja latencia)."""
    if file is None:
        raise HTTPException(status_code=400, detail="Adjunta 'file' (multipart) o usa /transcribe/json")
    audio_bytes = await file.read()
    mime = file.content_type or "audio/webm"
    result = await groq_stt.transcribe(audio_bytes, mime, language=language, prompt=prompt)
    return ok(result)


@router.post("/transcribe/json")
async def transcribe_json(req: TranscribeJSONRequest):
    """STT Groq — JSON + base64."""
    try:
        audio_bytes = base64.b64decode(req.audio, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Base64 invalido") from exc
    result = await groq_stt.transcribe(
        audio_bytes, req.mime_type, language=req.language, prompt=req.prompt
    )
    return ok(result)
