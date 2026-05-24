# MediNote - Backend 1 (IA)

FastAPI para chat con intencion, transcripcion de audio con Grok STT (Azure AI endpoint dedicado) y generacion de historial clinico (LLM).

## Requisitos

- Python 3.11+
- API keys si `MOCK_AI=false`

## Instalacion

```powershell
cd hackaton_backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Ejecutar

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docs: `http://localhost:8000/docs`

## Variables de entorno

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `MOCK_AI` | `true` | Demo sin API keys |
| `API_TIMEOUT_SEC` | `30` | Timeout STT/LLM |
| `RATE_LIMIT_PER_MINUTE` | `60` | Limite por IP |
| `MAX_AUDIO_MB` | `10` | Tamano maximo audio REST/WS |
| `MAX_WS_CHUNKS` | `500` | Fragmentos maximos por sesion WS |
| `WS_TRANSCRIBE_ON_INTERVAL` | `false` | Si `true`, partials mock cada N seg |
| `STT_PROVIDER` | `grok` | Proveedor de transcripcion |
| `STT_MODEL` | `grok-4-20-non-reasoning` | Modelo STT |
| `AZURE_AI_STT_ENDPOINT` | `https://scia.services.ai.azure.com/openai/v1/` | Endpoint STT (no GPT endpoint) |
| `AZURE_API_KEY` | `""` | API key para Grok STT |
| `LLM_PROVIDER` | `openai` | Proveedor LLM de chat/historial |
| `LLM_MODEL` | `gpt-4o-mini` | Modelo LLM de chat/historial |
| `OPENAI_API_KEY` | `""` | API key del LLM (si aplica) |

## Modo demo (`MOCK_AI=true`)

Sin API keys: transcripcion simulada, intenciones por reglas e historial derivado del transcript.

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/health` | Estado servicio |
| POST | `/chat` | Texto o audio base64 -> intencion + mensaje |
| POST | `/historiales` | Transcript -> JSON clinico + `historial_id` |
| WS | `/ws/transcribe` | Transcripcion en vivo (Grok STT al `stop`) |

## WebSocket `/ws/transcribe`

1. `{"type":"start","session_id":"abc","mime_type":"audio/webm"}`
2. `{"type":"audio","chunk":"<base64>"}` (repetir)
3. `{"type":"stop"}` -> `{"type":"final","text":"transcripcion completa"}`

Importante: la transcripcion real con Grok STT ocurre al enviar `stop`, no por cada chunk.

## Contratos

- FE1 -> `POST /chat`, `WS /ws/transcribe`
- BE2 + FE2 -> objeto `historial` + `historial_id` de `POST /historiales`
