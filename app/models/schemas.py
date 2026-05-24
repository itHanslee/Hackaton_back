from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MedicamentoItem(BaseModel):
    nombre: str
    dosis: str = ""
    frecuencia: str = ""
    duracion: str = ""


class HistorialClinico(BaseModel):
    motivo_consulta: str
    sintomas: list[str] = Field(default_factory=list)
    diagnostico: str
    plan_tratamiento: str
    medicamentos_sugeridos: list[MedicamentoItem] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Unified chat body: text OR audio."""

    text: str | None = None
    audio: str | None = None
    mime_type: str = "audio/webm"
    generate_historial: bool = False

    @model_validator(mode="after")
    def text_or_audio(self) -> "ChatRequest":
        if not self.text and not self.audio:
            raise ValueError("Debe enviar 'text' o 'audio'")
        if self.text and self.audio:
            raise ValueError("Envíe solo 'text' o 'audio', no ambos")
        return self


IntentType = Literal[
    "agendar_cita",
    "consulta_medica",
    "generar_historial",
    "desconocido",
]


class ChatResponseData(BaseModel):
    message: str
    detected_intent: IntentType
    slot_suggested: str | None = None
    transcript: str | None = None
    historial: HistorialClinico | None = None


class GenerateHistorialRequest(BaseModel):
    session_id: str | None = None
    transcript: str = Field(..., min_length=1)
    context: dict[str, str] | None = None


class GenerateHistorialResponseData(BaseModel):
    historial_id: UUID
    historial: HistorialClinico
    session_id: str | None = None

class PacienteBase(BaseModel):
    cedula: str
    nombre: str
    fecha_nacimiento: str
    genero: str
    telefono: str | None = None
    eps_id: int

class PacienteResponse(PacienteBase):
    id: int
    class Config:
        from_attributes = True

class MedicoBase(BaseModel):
    cedula: str
    nombre: str
    especialidad: str
    eps_id: int

class MedicoResponse(MedicoBase):
    id: int
    class Config:
        from_attributes = True

class Slot(BaseModel):
    start_time: str
    end_time: str
    available: bool

class CitaCreate(BaseModel):
    paciente_id: int
    medico_id: int
    fecha_hora: str
    motivo: str

class CitaResponse(CitaCreate):
    id: int
    estado: str
    class Config:
        from_attributes = True

class MedicamentoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str | None = None
    eps_id: int
    class Config:
        from_attributes = True

class HistorialCreate(BaseModel):
    consulta_id: int
    motivo_consulta: str
    sintomas: str
    diagnostico: str
    plan_tratamiento: str
    medicamentos_sugeridos: str | None = None
    confirmado_por_medico: bool = False
    pdf_path: str | None = None

class HistorialResponse(HistorialCreate):
    id: int
    created_at: str | None = None
    class Config:
        from_attributes = True

class ConsultaBase(BaseModel):
    cita_id: int
    audio_path: str | None = None
    transcripcion: str | None = None

class ConsultaCreate(ConsultaBase):
    pass

class ConsultaResponse(ConsultaBase):
    id: int
    created_at: str | None = None
    class Config:
        from_attributes = True

