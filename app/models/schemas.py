from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


NO_DEFINIDO = "No definido"


class MedicamentoDisponible(BaseModel):
    nombre: str = NO_DEFINIDO
    dosis: str = NO_DEFINIDO
    frecuencia: str = NO_DEFINIDO


class MedicamentoIdeal(BaseModel):
    nombre: str = NO_DEFINIDO
    razon: str = NO_DEFINIDO


class MedicamentosHistorial(BaseModel):
    disponibles_eps: list[MedicamentoDisponible] = Field(default_factory=list)
    ideales_sugeridos: list[MedicamentoIdeal] = Field(default_factory=list)


class HistorialClinico(BaseModel):
    motivo_consulta: str = NO_DEFINIDO
    sintomas: list[str] = Field(default_factory=list)
    diagnostico: str = NO_DEFINIDO
    plan_tratamiento: str = NO_DEFINIDO
    alergias: str = NO_DEFINIDO
    notas_adicionales: str = NO_DEFINIDO
    medicamentos: MedicamentosHistorial = Field(default_factory=MedicamentosHistorial)
    requiere_incapacidad: bool = False
    incapacidad_dias: int | None = None
    incapacidad_recomendaciones: str | None = None


class ChatRequest(BaseModel):
    text: str | None = None
    audio: str | None = None
    mime_type: str = "audio/webm"
    generate_historial: bool = False
    paciente_id: int | None = None

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


class AppointmentSlots(BaseModel):
    fecha: str | None = None
    hora: str | None = None
    especialidad: str | None = None


class ChatResponseData(BaseModel):
    message: str
    detected_intent: IntentType
    slot_suggested: str | None = None
    appointment_slots: AppointmentSlots | None = None
    transcript: str | None = None
    historial: HistorialClinico | None = None


class GenerateHistorialRequest(BaseModel):
    session_id: str | None = None
    transcript: str = Field(..., min_length=1)
    context: dict[str, str] | None = None
    paciente_id: int | None = None


class GenerateHistorialResponseData(BaseModel):
    historial_id: UUID
    historial: HistorialClinico
    session_id: str | None = None


class HistorialConfirmRequest(BaseModel):
    consulta_id: int
    motivo_consulta: str
    sintomas: list[str] | str = ""
    diagnostico: str
    plan_tratamiento: str
    alergias: str | None = None
    notas_adicionales: str | None = None
    medicamentos: dict = Field(default_factory=dict)
    confirmado_por_medico: bool = True
    requiere_incapacidad: bool = False
    incapacidad_dias: int | None = None
    enviar_informe_email: bool = False


class HistorialUpdateRequest(BaseModel):
    """PUT /historiales/{id} — campos del frontend Monwe."""

    motivo: str | None = None
    motivo_consulta: str | None = None
    sintomas: list[str] | str | None = None
    diagnostico: str | None = None
    plan: str | None = None
    plan_tratamiento: str | None = None
    alergias: str | None = None
    notas_adicionales: str | None = None
    medicamentos: list | dict | None = None
    requiere_incapacidad: bool | None = None
    incapacidad_dias: int | None = Field(default=None, ge=1, le=365)
    incapacidad_recomendaciones: str | None = None
    paciente_eps: str | None = None

    def to_apply_dict(self) -> dict:
        return self.model_dump(exclude_none=True)

class PacienteBase(BaseModel):
    cedula: str
    nombre: str
    fecha_nacimiento: str
    genero: str
    telefono: str | None = None
    eps_id: int


class PacienteResponse(PacienteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class MedicoBase(BaseModel):
    cedula: str
    nombre: str
    especialidad: str
    eps_id: int


class MedicoResponse(MedicoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tiene_firma: bool = False


class EPSResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    tiene_logo: bool = False


class MedicoProfileResponse(MedicoResponse):
    email: str | None = None
    firma_url: str | None = None


class SlotResponse(BaseModel):
    id: str
    datetime: str
    available: bool


class CitaCreate(BaseModel):
    paciente_id: int
    medico_id: int
    fecha_hora: str
    motivo: str


class CitaResponse(CitaCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    estado: str


class MedicoCitaCalendarItem(CitaResponse):
    paciente_nombre: str
    paciente_cedula: str


class MedicamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    descripcion: str | None = None
    eps_id: int


class HistorialCreate(BaseModel):
    consulta_id: int
    motivo_consulta: str
    sintomas: str
    diagnostico: str
    plan_tratamiento: str
    medicamentos_sugeridos: dict | None = None
    confirmado_por_medico: bool = False
    pdf_path: str | None = None


class HistorialResponse(HistorialCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: str | None = None


class ConsultaBase(BaseModel):
    cita_id: int
    audio_path: str | None = None
    transcripcion: str | None = None


class ConsultaCreate(ConsultaBase):
    pass


class ConsultaResponse(ConsultaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: str | None = None
