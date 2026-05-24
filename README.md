# MediNote AI — Backend unificado

FastAPI backend para hackathon MediNote: IA clínica (Gemini), agente conversacional (Azure OpenAI + Groq STT), auth JWT, citas, historiales con PDF/firma y correo SMTP.

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

Ver flujos del agente en la sección WebSocket más abajo.

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

Desde la **raíz del repo** (`HACKATON2026_BACK`), no desde subcarpetas:

```powershell
cd C:\Users\danic\OneDrive\Documents\HACKATON2026_BACK
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docs: http://localhost:8000/docs · Health: http://localhost:8000/health

Con `DEBUG=true`, frontend local: http://127.0.0.1:8000/dev-ui/

## Demo sin API keys

En `.env`:

```
MOCK_AI=true
AUTH_DISABLED=true
```

## Credenciales demo (seed)

Requieren `SEED_ON_STARTUP=true` (default). El login usa **cédula + contraseña** (no el email).

### Médicos

| Cédula | Contraseña | Nombre | Email | Especialidad | EPS |
|--------|------------|--------|-------|--------------|-----|
| `1001` | `medico123` | Dr. Ana García | ana.garcia@medinote.local | Medicina General | Sura |
| `1002` | `medico123` | Dr. Luis Pérez | luis.perez@medinote.local | Cardiología | Sura |
| `1003` | `medico123` | Dra. María López | maria.lopez@medinote.local | Endocrinología | Sanitas |

### Pacientes

| Cédula | Contraseña | Nombre | Email | EPS |
|--------|------------|--------|-------|-----|
| `2001` | `paciente123` | Carlos Rodríguez | carlos.rodriguez@example.com | Sura |
| `2002` | `paciente123` | Laura Martínez | laura.martinez@example.com | Sanitas |

### Login

```http
POST /auth/medico/login
Content-Type: application/json

{ "cedula": "1001", "password": "medico123" }
```

```http
POST /auth/paciente/login
Content-Type: application/json

{ "cedula": "2001", "password": "paciente123" }
```

La respuesta incluye `access_token` (JWT) para el header `Authorization: Bearer <token>`.

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
| POST | `/historiales/generate` | Generar JSON clínico (sin persistir) |
| POST | `/historiales` | Confirmar historial + PDF + email |
| GET | `/historiales/{id}/pdf` | Descargar PDF |
| POST | `/consultas/procesar` | Audio → transcripción + historial |
| WS | `/ws/transcribe` | Transcripción en vivo (Gemini) |
| WS | `/ws/chat` | Agente conversacional con tools |
| POST | `/transcribe` | STT Groq (multipart) |
| GET/POST | `/pacientes`, `/citas`, `/medicos` | CRUD agendamiento |
| GET | `/citas/calendario?medico_id=` | Calendario por médico |
| GET | `/medicos/me/citas?month=YYYY-MM` | Citas del médico autenticado |
| POST | `/medicos/me/firma` | Subir firma médico |
| POST | `/eps/{id}/logo` | Subir logo EPS |

## Estructura del proyecto (un solo backend)

```
HACKATON2026_BACK/
├── app/                    # ← ÚNICO backend FastAPI (uvicorn app.main:app)
│   ├── main.py
│   ├── core/               # config, auth, security, middleware
│   ├── db/                 # database, schema_sync, seed
│   ├── models/             # SQLAlchemy + Pydantic
│   ├── routers/            # HTTP + WebSocket
│   └── services/           # IA, agente, PDF, email
├── tests/
├── fixtures/
├── requirements.txt
├── .env.example
└── README.md
```

**No uses una carpeta `backend/` separada** — todo el código está en `app/` en la raíz.

## Tests

```powershell
pytest tests/ -q
```

45 tests — usan `MOCK_AI=true`, `AUTH_DISABLED=true` y SQLite de prueba.

## Notas

- El agente (`/ws/chat`) escribe directamente en BD; un solo puerto **8000**.
- Copia tu configuración a `.env` en la raíz (ver `.env.example`).
- Frontend demo local en `frontend/` (gitignored).
