import base64

from starlette.testclient import TestClient

from app.main import app


def test_ws_transcribe_start_stop():
    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json(
            {"type": "start", "session_id": "test-1", "mime_type": "audio/webm"}
        )
        started = ws.receive_json()
        assert started["type"] == "started"

        chunk = base64.b64encode(b"\x00" * 128).decode("ascii")
        ws.send_json({"type": "audio", "chunk": chunk})

        ws.send_json({"type": "stop"})
        final = ws.receive_json()
        assert final["type"] == "final"
        assert "text" in final
