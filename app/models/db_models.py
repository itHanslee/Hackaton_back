from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


def _uuid_str() -> str:
    return str(uuid4())


class EPS(Base):
    __tablename__ = "eps"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, index=True)
    logo_path = Column(String, nullable=True)

    pacientes = relationship("Paciente", backref="eps")
    medicos = relationship("Medico", backref="eps")
    medicamentos = relationship("MedicamentoEPS", backref="eps")


class Paciente(Base):
    __tablename__ = "pacientes"
    id = Column(Integer, primary_key=True, index=True)
    cedula = Column(String, unique=True, index=True)
    nombre = Column(String, index=True)
    fecha_nacimiento = Column(String)
    genero = Column(String)
    tipo_documento = Column(String, default="CC")
    tipo_paciente = Column(String, default="Contributivo")
    telefono = Column(String)
    email = Column(String, nullable=True, index=True)
    password_hash = Column(String, nullable=True)
    eps_id = Column(Integer, ForeignKey("eps.id"))
    datos_incapacidad_json = Column(JSON, nullable=True)
    radicaciones_json = Column(JSON, nullable=True)
    citas = relationship("Cita", back_populates="paciente")


class Medico(Base):
    __tablename__ = "medicos"
    id = Column(Integer, primary_key=True, index=True)
    cedula = Column(String, unique=True, index=True)
    nombre = Column(String, index=True)
    especialidad = Column(String)
    email = Column(String, nullable=True, index=True)
    password_hash = Column(String, nullable=True)
    eps_id = Column(Integer, ForeignKey("eps.id"))
    firma_path = Column(String, nullable=True)
    firma_imagen = Column(LargeBinary, nullable=True)
    citas = relationship("Cita", back_populates="medico")


class Cita(Base):
    __tablename__ = "citas"
    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"))
    medico_id = Column(Integer, ForeignKey("medicos.id"))
    fecha_hora = Column(DateTime)
    motivo = Column(String)
    estado = Column(String, default="pendiente")
    paciente = relationship("Paciente", back_populates="citas")
    medico = relationship("Medico", back_populates="citas")
    consultas = relationship("Consulta", back_populates="cita")


class Consulta(Base):
    __tablename__ = "consultas"
    id = Column(Integer, primary_key=True, index=True)
    cita_id = Column(Integer, ForeignKey("citas.id"))
    audio_path = Column(String)
    transcripcion = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    cita = relationship("Cita", back_populates="consultas")
    historial = relationship("Historial", back_populates="consulta", uselist=False)


class Historial(Base):
    __tablename__ = "historiales"
    id = Column(Integer, primary_key=True, index=True)
    consulta_id = Column(Integer, ForeignKey("consultas.id"))
    motivo_consulta = Column(Text)
    sintomas = Column(Text)
    diagnostico = Column(Text)
    plan_tratamiento = Column(Text)
    medicamentos_sugeridos = Column(JSON)
    confirmado_por_medico = Column(Boolean, default=False)
    pdf_path = Column(String)
    incapacidad_pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    consulta = relationship("Consulta", back_populates="historial")
    radicacion_jobs = relationship("IncapacidadRadicacionJob", back_populates="historial")


class IncapacidadRadicacionJob(Base):
    __tablename__ = "incapacidad_radicacion_jobs"

    id = Column(String(36), primary_key=True, default=_uuid_str)
    historial_id = Column(Integer, ForeignKey("historiales.id"), index=True, nullable=False)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=True)
    estado = Column(String(32), default="pendiente", index=True)
    paso_actual = Column(Integer, default=0)
    pdf_path = Column(String, nullable=True)
    ocr_json = Column(JSON, nullable=True)
    rethus_json = Column(JSON, nullable=True)
    adres_json = Column(JSON, nullable=True)
    reporte_json = Column(JSON, nullable=True)
    score = Column(Integer, nullable=True)
    recomendacion = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    historial = relationship("Historial", back_populates="radicacion_jobs")


class MedicamentoEPS(Base):
    __tablename__ = "medicamentos_eps"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    descripcion = Column(String)
    nombre_generico = Column(String, nullable=True)
    nombre_comercial = Column(String, nullable=True)
    categoria = Column(String, nullable=True)
    diagnosticos_aplica = Column(JSON, nullable=True)
    disponible = Column(Boolean, default=True)
    eps_id = Column(Integer, ForeignKey("eps.id"))
