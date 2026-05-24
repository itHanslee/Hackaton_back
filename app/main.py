import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.auth_middleware import AuthMiddleware
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RateLimitMiddleware
from app.core.responses import ok
from app.db.database import SessionLocal
from app.db.schema_sync import sync_schema
from app.db.seed import seed_database
from app.routers import (
    agent,
    auth,
    chat,
    citas,
    consultas,
    eps,
    historiales,
    medicamentos,
    medicos,
    pacientes,
    transcribe,
)
from app.services import groq_stt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await groq_stt.init_http_client()
    sync_schema()
    if settings.seed_on_startup:
        db = SessionLocal()
        try:
            seed_database(db)
        except Exception:
            logger.exception("Seed failed — continuing without demo data")
            db.rollback()
        finally:
            db.close()

    if settings.mock_ai:
        logger.info("MOCK_AI=true — IA desactivada (respuestas de prueba).")
    elif not (settings.google_api_key or "").strip():
        logger.warning("GOOGLE_API_KEY no configurada.")
    else:
        try:
            import google.genai  # noqa: F401
        except ImportError:
            logger.warning("Falta google-genai.")
        else:
            logger.info("IA activa: Gemini (%s).", settings.gemini_model)

    yield
    await groq_stt.close_http_client()


app = FastAPI(
    title=settings.app_name,
    description="MediNote AI — Backend unificado",
    version="0.3.0",
    debug=settings.debug,
    lifespan=lifespan,
)

register_exception_handlers(app)

# CORSMiddleware debe ser el más externo (se añade al final).
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
if settings.cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    _cors_origins = settings.effective_cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins if _cors_origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(historiales.router)
app.include_router(transcribe.router)
app.include_router(agent.router)
app.include_router(citas.router)
app.include_router(medicos.router)
app.include_router(eps.router)
app.include_router(pacientes.router)
app.include_router(medicamentos.router)
app.include_router(consultas.router)

_frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
if settings.debug and _frontend_dir.is_dir():
    app.mount(
        "/dev-ui",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="dev-ui",
    )
    logger.info("Frontend de prueba: http://127.0.0.1:%s/dev-ui/", settings.port)


@app.get("/health")
async def health():
    return ok({
        "status": "ok",
        "gemini_configured": bool(settings.google_api_key),
        "agent": {
            "azure_configured": bool(settings.azure_api_key),
            "groq_configured": bool(settings.groq_api_key),
        },
        "auth_disabled": settings.auth_disabled,
    })
