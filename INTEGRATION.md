# MediNote — Backend unificado (puerto 8000)

Un solo servicio FastAPI en `app/` integra:

- **Gemini** — chat REST, historiales, transcripción WS
- **Agente conversacional** — `WS /ws/chat` (Azure OpenAI + tools directas a BD)
- **Groq STT** — `POST /transcribe` (REST rápido para voz)
- **Auth JWT** — login paciente/médico, middleware por rol
- **Historiales** — generar, confirmar, PDF con firma/logo, email SMTP
- **CRUD** — pacientes, médicos, citas, EPS, medicamentos, consultas

## Arranque

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Agente conversacional

`ws://localhost:8000/ws/chat`

```json
{"text": "Quiero agendar cita con cardiologo"}
```

Tools: `crear_paciente`, `monitor_paciente`, `generar_historial`, `buscar_medico`, `crear_cita`.

Las tools escriben directamente en la BD (sin microservicio intermedio).

## Auth

Header: `Authorization: Bearer <token>`

Rutas públicas: `/health`, `/auth/*/login`, `POST /citas`, `POST /pacientes`, `GET /medicos`, `GET /eps`, `POST /transcribe*`.

WebSocket `/ws/chat` y `/ws/transcribe` no pasan por auth HTTP.

## Variables clave

Ver `.env.example` — `GOOGLE_API_KEY`, `AZURE_API_KEY`, `GROQ_API_KEY`, `JWT_SECRET`, `SMTP_*`.
