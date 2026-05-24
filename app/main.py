import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RateLimitMiddleware
from app.core.responses import ok
from app.routers import chat, historiales, transcribe, citas, medicos, pacientes, medicamentos, consultas
from app.db.database import Base, SessionLocal, engine
from app.models.db_models import EPS, Medico, Paciente

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Backend 1 — IA: transcripción, chat e historial clínico (MediNote AI)",
    version="0.1.0",
    debug=settings.debug,
)

register_exception_handlers(app)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(historiales.router)
app.include_router(transcribe.router)
app.include_router(citas.router)
app.include_router(medicos.router)
app.include_router(pacientes.router)
app.include_router(medicamentos.router)
app.include_router(consultas.router)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(EPS).count() == 0:
            db.add_all([EPS(id=1, nombre="Sura"), EPS(id=2, nombre="Sanitas"), EPS(id=3, nombre="Nueva EPS")])
        if db.query(Medico).count() == 0:
            db.add_all([
                Medico(id=1, cedula="900001", nombre="Dra. Ana Ruiz", especialidad="Medicina general", eps_id=1),
                Medico(id=2, cedula="900002", nombre="Dr. Carlos Mejia", especialidad="Medicina interna", eps_id=2),
                Medico(id=3, cedula="900003", nombre="Dra. Laura Gomez", especialidad="Pediatria", eps_id=3),
            ])
        if db.query(Paciente).count() == 0:
            db.add_all([
                Paciente(id=1, cedula="1023456789", nombre="Maria Garcia Lopez", fecha_nacimiento="", genero="", telefono="3001234567", eps_id=1),
                Paciente(id=2, cedula="100000002", nombre="Carlos Rodriguez", fecha_nacimiento="", genero="", telefono="3000000002", eps_id=2),
            ])
        db.commit()
    finally:
        db.close()



@app.get("/health")
async def health():
    return ok({"status": "ok"})
