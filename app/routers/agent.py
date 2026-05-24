"""Agente conversacional: WebSocket /ws/chat y transcripcion Groq REST."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid

from fastapi import APIRouter, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.responses import ok
from app.services import chat_agent, groq_stt

router = APIRouter(tags=["agent"])
logger = logging.getLogger(__name__)


class TranscribeJSONRequest(BaseModel):
    audio: str
    mime_type: str = "audio/webm"
    language: str | None = "es"
    prompt: str | None = None


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            force_historial = data.get("generate_historial", False)
            tool_hint = data.get("tool_hint", "")

            intent = chat_agent.classify_intent(text)
            if force_historial:
                intent = "generar_historial"

            if tool_hint and tool_hint in chat_agent.TOOLS:
                tool_name = tool_hint
            else:
                tool_name = chat_agent.INTENT_TO_TOOL.get(intent, "consulta_medica")

            tool_info = chat_agent.TOOLS[tool_name]
            tool_id = f"tool-{uuid.uuid4().hex[:8]}"

            await websocket.send_json({
                "type": "tool_start",
                "tool": {"id": tool_id, "name": tool_name, "label": tool_info["label"]},
            })

            result = await chat_agent.execute_tool(tool_name, text, extra_payload=data)

            await websocket.send_json({
                "type": "tool_result",
                "tool_id": tool_id,
                "success": result.get("success", False),
                "result": result,
            })

            reply = chat_agent.generate_reply(intent, text, tool_name, result)
            words = reply.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                await websocket.send_json({"type": "chunk", "text": chunk})
                await asyncio.sleep(0.02)

            await websocket.send_json({
                "type": "done",
                "intent": intent,
                "patient": result.get("patient"),
                "historial": result.get("historial"),
                "cita": result.get("cita"),
                "tool_name": tool_name,
            })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("WS chat error")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


@router.post("/transcribe")
async def transcribe_multipart(
    file: UploadFile | None = File(default=None),
    language: str | None = Form(default="es"),
    prompt: str | None = Form(default=None),
):
    if file is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Adjunta 'file' (multipart) o usa /transcribe/json")
    audio_bytes = await file.read()
    mime = file.content_type or "audio/webm"
    result = await groq_stt.transcribe(audio_bytes, mime, language=language, prompt=prompt)
    return ok(result)


@router.post("/transcribe/json")
async def transcribe_json(req: TranscribeJSONRequest):
    from fastapi import HTTPException
    try:
        audio_bytes = base64.b64decode(req.audio, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Base64 invalido") from exc
    result = await groq_stt.transcribe(
        audio_bytes, req.mime_type, language=req.language, prompt=req.prompt
    )
    return ok(result)
