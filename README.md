# MediNote AI — Backend unificado

FastAPI backend para hackathon MediNote: IA clínica (Gemini), agente conversacional (Azure OpenAI + Groq STT), auth JWT, citas, historiales con PDF/firma y correo SMTP.

**Un solo servicio en el puerto 8000.** No hay microservicios separados.

## Arquitectura

```
Cliente (frontend / WS)
        │
        ▼
   app/main.py  (:8000)
        │
   ┌────┴────────────────────────────────────┐
   │ Routers                                  │
   │  auth, chat, historiales, transcribe     │
   │  agent (/ws/chat), citas, pacientes      │
   │  medicos, medicamentos, consultas, eps   │
   └────┬────────────────────────────────────┘
        │
   ┌────┴────────────────────────────────────┐
   │ Services                                 │
   │  ai (Gemini STT/LLM)                     │
   │  chat_agent (Azure tools → BD directa)   │
   │  groq_stt, email, pdf, slots, medicamentos│
   └────┬────────────────────────────────────┘
        ▼
   PostgreSQL / SQLite
```

Ver `INTEGRATION.md` para contratos WebSocket y flujos del agente.

## Requisitos

- Python 3.11+
- `GOOGLE_API_KEY` para chat/historial REST y transcripción WS (Gemini)
- `AZURE_API_KEY` + `GROQ_API_KEY` opcionales para el agente conversacional
- PostgreSQL en producción (`DATABASE_URL`)

## Instalación

```powershell
cd HACKATON2026_BACK
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Ejecutar

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docs: http://localhost:8000/docs

## Demo sin API keys

En `.env`:

```
MOCK_AI=true
AUTH_DISABLED=true
```

## Credenciales demo (con seed)

| Rol | Usuario | Contraseña |
|-----|---------|------------|
| Médico | `1001` | `medico123` |
| Paciente | `2001` | `paciente123` |

Login: `POST /auth/medico/login` o `POST /auth/paciente/login`

## Variables de entorno principales

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | SQLite local o PostgreSQL |
| `MOCK_AI` | Demo sin llamadas a IA |
| `GOOGLE_API_KEY` | Gemini STT + LLM (REST + WS transcribe) |
| `GEMINI_MODEL` | Modelo Gemini |
| `AZURE_API_KEY` | Agente conversacional Azure OpenAI |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment del agente |
| `GROQ_API_KEY` | STT rápido (`POST /transcribe`) |
| `JWT_SECRET` | Firma de tokens |
| `AUTH_DISABLED` | Bypass auth (desarrollo) |
| `SMTP_*` | Email al confirmar historial |
| `SEED_ON_STARTUP` | Datos demo al arrancar |

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado + IA/agente |
| POST | `/auth/medico/login` | Login médico |
| POST | `/auth/paciente/login` | Login paciente |
| POST | `/chat` | Intención + mensaje (Gemini) |
| POST | `/historiales` | Generar historial clínico |
| POST | `/historiales/{id}/confirm` | Confirmar + PDF + email |
| GET | `/historiales/{id}/pdf` | Descargar PDF |
| WS | `/ws/transcribe` | Transcripción en vivo (Gemini) |
| WS | `/ws/chat` | Agente conversacional con tools |
| POST | `/transcribe` | STT Groq (multipart) |
| GET/POST | `/pacientes`, `/citas`, `/medicos` | CRUD agendamiento |
| POST | `/medicos/me/firma` | Subir firma médico |
| POST | `/eps/{id}/logo` | Subir logo EPS |

## Estructura del proyecto

```
app/
├── main.py              # Entry point FastAPI
├── core/                # config, auth, security, middleware
├── db/                  # database, schema_sync, seed
├── models/              # SQLAlchemy + Pydantic schemas
├── routers/             # HTTP + WebSocket endpoints
└── services/            # IA, agente, PDF, email, slots
tests/                   # pytest
fixtures/                # datos de prueba
```

## Tests

```powershell
pytest tests/ -q
```

Los tests usan `MOCK_AI=true`, `AUTH_DISABLED=true` y SQLite de prueba.

## Notas

- El agente (`/ws/chat`) escribe directamente en BD; no requiere segundo servicio.
- Carpeta `backend/` en el repo es legacy local (gitignored en su `.env`); **canónico es `app/` en la raíz**.
- Frontend demo local en `frontend/` (gitignored).
