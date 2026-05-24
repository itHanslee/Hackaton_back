from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base

class EPS(Base):
    __tablename__ = "eps"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, index=True)

class Paciente(Base):
    __tablename__ = "pacientes"
    id = Column(Integer, primary_key=True, index=True)
    cedula = Column(String, unique=True, index=True)
    nombre = Column(String, index=True)
    fecha_nacimiento = Column(String)
    genero = Column(String)
    telefono = Column(String)
    eps_id = Column(Integer, ForeignKey("eps.id"))

class Medico(Base):
    __tablename__ = "medicos"
    id = Column(Integer, primary_key=True, index=True)
    cedula = Column(String, unique=True, index=True)
    nombre = Column(String, index=True)
    especialidad = Column(String)
    eps_id = Column(Integer, ForeignKey("eps.id"))

class Cita(Base):
    __tablename__ = "citas"
    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"))
    medico_id = Column(Integer, ForeignKey("medicos.id"))
    fecha_hora = Column(DateTime)
    motivo = Column(String)
    estado = Column(String, default="programada")

class Consulta(Base):
    __tablename__ = "consultas"
    id = Column(Integer, primary_key=True, index=True)
    cita_id = Column(Integer, ForeignKey("citas.id"))
    audio_path = Column(String)
    transcripcion = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Historial(Base):
    __tablename__ = "historiales"
    id = Column(Integer, primary_key=True, index=True)
    consulta_id = Column(Integer, ForeignKey("consultas.id"))
    motivo_consulta = Column(Text)
    sintomas = Column(Text)
    diagnostico = Column(Text)
    plan_tratamiento = Column(Text)
    medicamentos_sugeridos = Column(Text)
    confirmado_por_medico = Column(Boolean, default=False)
    pdf_path = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class MedicamentoEPS(Base):
    __tablename__ = "medicamentos_eps"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    descripcion = Column(String)
    eps_id = Column(Integer, ForeignKey("eps.id"))
