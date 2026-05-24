"""Agente conversacional: WebSocket /ws/chat."""

from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import chat_agent

router = APIRouter(tags=["agent"])
logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ws_stream")


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    booking_context: dict[str, object] = {}
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
                tool_name = chat_agent.choose_tool_with_ai(
                    text,
                    intent,
                    history if isinstance(history, list) else None,
                )

            if tool_name == "crear_cita":
                if "medico_id" not in data and booking_context.get("medico_id") is not None:
                    data["medico_id"] = booking_context["medico_id"]
                if "slot_id" not in data and booking_context.get("slot_id") is not None:
                    data["slot_id"] = booking_context["slot_id"]

            tool_info = chat_agent.TOOLS[tool_name]
            tool_id = f"tool-{uuid.uuid4().hex[:8]}"

            await websocket.send_json({
                "type": "tool_start",
                "tool": {"id": tool_id, "name": tool_name, "label": tool_info["label"]},
            })

            result = await chat_agent.execute_tool(tool_name, text, extra_payload=data)

            if tool_name == "buscar_medico" and result.get("success"):
                medicos = result.get("medicos") or []
                slots = result.get("slots") or []
                if medicos and slots:
                    try:
                        booking_context["medico_id"] = int(medicos[0]["id"])
                        booking_context["slot_id"] = int(slots[0]["id"])
                    except Exception:
                        pass

            await websocket.send_json({
                "type": "tool_result",
                "tool_id": tool_id,
                "success": result.get("success", False),
                "result": result,
            })

            loop = asyncio.get_event_loop()
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            def _stream_into_queue():
                try:
                    for token in chat_agent.stream_reply(
                        intent,
                        text,
                        tool_name,
                        result,
                        conversation_history=history if isinstance(history, list) else None,
                    ):
                        loop.call_soon_threadsafe(queue.put_nowait, token)
                except Exception as exc:
                    logger.warning("stream_reply error: %s", exc)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            loop.run_in_executor(_executor, _stream_into_queue)

            while True:
                token = await queue.get()
                if token is None:
                    break
                await websocket.send_json({"type": "chunk", "text": token})

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
