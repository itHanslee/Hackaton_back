"""Agente conversacional: WebSocket /ws/chat."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import chat_agent

router = APIRouter(tags=["agent"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            force_historial = data.get("generate_historial", False)
            tool_hint = data.get("tool_hint", "")
            history = data.get("history", [])

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

            reply = chat_agent.generate_reply(
                intent,
                text,
                tool_name,
                result,
                conversation_history=history if isinstance(history, list) else None,
            )
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
