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

## Credenciales de login

El login usa **cédula + contraseña** (no el email). En BD las contraseñas se guardan con **Argon2** (`$argon2id$...`); eso es normal: el backend compara tu texto plano contra ese hash en `POST /auth/*/login`.

### BD compartida Hackathon (PostgreSQL remoto)

Si tu `.env` apunta al PostgreSQL del equipo y **ya tiene datos**, usa las cédulas reales de esa BD (no las del seed local):

| Rol | Cédula | Contraseña | Nombre |
|-----|--------|------------|--------|
| Médico | `999888777` | `medico123` | Dra. Ana García |
| Paciente | `111000111` | `paciente123` | Carlos Rodríguez |

> Verificado contra la BD remota del proyecto: `1001` / `2001` **no existen** ahí; las cédulas largas anteriores son las correctas para ese entorno.

### Seed local (SQLite o BD vacía)

Con `SEED_ON_STARTUP=true`, si no existe EPS «Sura», se crean usuarios demo con cédulas cortas:

**Médicos** (contraseña común: `medico123`)

| Cédula | Nombre | Email | Especialidad | EPS |
|--------|--------|-------|--------------|-----|
| `1001` | Dr. Ana García | ana.garcia@medinote.local | Medicina General | Sura |
| `1002` | Dr. Luis Pérez | luis.perez@medinote.local | Cardiología | Sura |
| `1003` | Dra. María López | maria.lopez@medinote.local | Endocrinología | Sanitas |

**Pacientes** (contraseña común: `paciente123`)

| Cédula | Nombre | Email | EPS |
|--------|--------|-------|-----|
| `2001` | Carlos Rodríguez | carlos.rodriguez@example.com | Sura |
| `2002` | Laura Martínez | laura.martinez@example.com | Sanitas |

Si la BD ya tiene EPS «Sura» pero usuarios sin `password_hash`, el arranque solo rellena hash/email faltantes — **no cambia cédulas ni contraseñas ya guardadas**.

### Ejemplo de login

```http
POST /auth/medico/login
Content-Type: application/json

{ "cedula": "999888777", "password": "medico123" }
```

```http
POST /auth/paciente/login
Content-Type: application/json

{ "cedula": "111000111", "password": "paciente123" }
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
