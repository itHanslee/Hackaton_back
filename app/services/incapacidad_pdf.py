"""Genera PDF de incapacidad laboral (formato Melanys) desde datos de la BD."""

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from app.core.config import get_settings
from app.services.historial_bundle import HistorialBundle, incapacidad_dias, incapacidad_fechas
from app.services.paciente_incapacidad import build_paciente_incapacidad_datos
from app.services.pdf import _append_medico_firma


@dataclass
class IncapacidadPdfData:
    numero_incapacidad: str
    fecha_documento: str
    paciente_nombre: str
    paciente_tipo_documento: str
    paciente_numero_documento: str
    tipo_paciente: str
    sexo: str
    fecha_nacimiento: str
    edad_texto: str
    eps_detectada: str
    entidad_codigo: str
    medico_nombre: str
    registro_medico: str
    medico_especialidad: str
    diagnostico_codigo: str
    diagnostico_descripcion: str
    diagnostico_relacionado: str
    fecha_inicio: str
    fecha_fin: str
    dias: int
    grupo_servicio: str
    modalidad_servicio: str
    origen: str
    causa: str
    incapacidad_retroactiva: str
    prorroga: str
    motivo: str
    sintomas: str


_CIE10_RE = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b", re.IGNORECASE)


def _extract_cie10(diagnostico: str | None) -> tuple[str, str]:
    text = (diagnostico or "").strip()
    if not text:
        return "R69", "Diagnóstico no especificado"
    match = _CIE10_RE.search(text)
    if match:
        code = match.group(1).upper()
        desc = text.replace(match.group(0), "").strip(" -–—:")
        return code, desc or text
    return "R69", text


def _fmt_fecha(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        return f"{value.day}/{meses[value.month - 1]}/{value.year}"
    return str(value)


def build_incapacidad_data(
    bundle: HistorialBundle,
    dias_override: int | None = None,
) -> IncapacidadPdfData:
    historial = bundle.historial
    paciente = bundle.paciente
    medico = bundle.medico
    eps = bundle.eps
    paciente_datos = build_paciente_incapacidad_datos(paciente, eps) if paciente else {}

    dias = incapacidad_dias(historial, dias_override)
    inicio, fin = incapacidad_fechas(bundle, dias)
    cie, desc = _extract_cie10(historial.diagnostico)
    now = datetime.utcnow()
    numero = f"{historial.id:05d}"

    meds = historial.medicamentos_sugeridos or {}
    diag_rel = ""
    if isinstance(meds, dict):
        diag_rel = str(meds.get("diagnostico_relacionado") or "")

    return IncapacidadPdfData(
        numero_incapacidad=numero,
        fecha_documento=_fmt_fecha(now) + f" {now.strftime('%I:%M %p')}",
        paciente_nombre=paciente_datos.get("paciente_nombre") or (paciente.nombre if paciente else "PACIENTE"),
        paciente_tipo_documento=paciente_datos.get("paciente_tipo_documento") or "CC",
        paciente_numero_documento=paciente_datos.get("paciente_numero_documento") or (paciente.cedula if paciente else ""),
        tipo_paciente=paciente_datos.get("tipo_paciente") or "Contributivo",
        sexo=paciente_datos.get("sexo") or "—",
        fecha_nacimiento=paciente_datos.get("fecha_nacimiento") or (paciente.fecha_nacimiento if paciente else ""),
        edad_texto=paciente_datos.get("edad_texto") or "—",
        eps_detectada=paciente_datos.get("eps_detectada") or "EPS NO REGISTRADA",
        entidad_codigo=paciente_datos.get("entidad_codigo") or "",
        medico_nombre=(medico.nombre if medico else "MÉDICO TRATANTE"),
        registro_medico=(medico.cedula if medico else ""),
        medico_especialidad=(medico.especialidad if medico else "MEDICINA GENERAL"),
        diagnostico_codigo=cie,
        diagnostico_descripcion=desc,
        diagnostico_relacionado=diag_rel,
        fecha_inicio=_fmt_fecha(inicio),
        fecha_fin=_fmt_fecha(fin),
        dias=dias,
        grupo_servicio=paciente_datos.get("grupo_servicio") or "ConsultaExterna",
        modalidad_servicio=paciente_datos.get("modalidad_servicio") or "Intramural",
        origen=paciente_datos.get("origen") or "Comun",
        causa=paciente_datos.get("causa") or "",
        incapacidad_retroactiva=paciente_datos.get("incapacidad_retroactiva") or "Ninguna",
        prorroga=paciente_datos.get("prorroga") or "Ninguna",
        motivo=str(historial.motivo_consulta or ""),
        sintomas=str(historial.sintomas or ""),
    )


def _field(story: list, label: str, value: str, style) -> None:
    story.append(Paragraph(f"<b>{label}:</b> {value or '—'}", style))


def generate_incapacidad_pdf(
    bundle: HistorialBundle,
    dias_override: int | None = None,
) -> tuple[str, IncapacidadPdfData]:
    data = build_incapacidad_data(bundle, dias_override=dias_override)
    historial = bundle.historial
    medico = bundle.medico
    eps = bundle.eps
    settings = get_settings()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    title = styles["Heading1"]
    normal = styles["Normal"]
    story: list = []

    clinica = settings.empresa_razon_social or "CLÍNICA"
    direccion = settings.clinica_direccion
    telefono = settings.clinica_telefono
    nit = settings.clinica_nit or settings.empresa_nit or "—"
    reps = settings.clinica_reps

    story.append(Paragraph(f"Fecha Actual: {_fmt_fecha(datetime.utcnow())}", normal))
    _field(story, "Dirección", direccion, normal)
    story.append(Paragraph(f"<b>{clinica}</b>", styles["Heading2"]))
    _field(story, "Teléfono", telefono, normal)
    _field(story, "NIT", nit, normal)
    _field(story, "REPS", reps, normal)
    story.append(Spacer(1, 8))

    story.append(Paragraph("INCAPACIDAD MÉDICA", title))
    story.append(Paragraph(f"Nº {data.numero_incapacidad}", styles["Heading2"]))
    story.append(Spacer(1, 10))

    if eps and eps.logo_path and os.path.isfile(eps.logo_path):
        story.append(Image(eps.logo_path, width=80, height=40))
        story.append(Spacer(1, 8))

    story.append(Paragraph("<b>INFORMACIÓN GENERAL</b>", styles["Heading2"]))
    _field(story, "Fecha Documento", data.fecha_documento, normal)
    _field(story, "Médico", f"{data.registro_medico} {data.medico_nombre}", normal)
    story.append(
        Paragraph(
            f"<b>Información Paciente:</b> {data.paciente_nombre} "
            f"<b>Tipo Paciente:</b> {data.tipo_paciente} <b>Sexo:</b> {data.sexo}",
            normal,
        )
    )
    story.append(
        Paragraph(
            f"<b>Tipo Documento:</b> {data.paciente_tipo_documento} "
            f"<b>Número:</b> {data.paciente_numero_documento} "
            f"<b>Edad:</b> {data.edad_texto} <b>F. Nacimiento:</b> {data.fecha_nacimiento}",
            normal,
        )
    )
    entidad = f"{data.entidad_codigo} {data.eps_detectada}".strip()
    _field(story, "Entidad", entidad, normal)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>DETALLE DE LA INCAPACIDAD</b>", styles["Heading2"]))
    story.append(
        Paragraph(
            f"<b>Días de Incapacidad:</b> {data.dias} "
            f"<b>Fecha Inicial:</b> {data.fecha_inicio} <b>Fecha Final:</b> {data.fecha_fin}",
            normal,
        )
    )
    story.append(Paragraph("SE ABRE FOLIO PARA INCAPACIDAD MÉDICA", normal))
    story.append(Spacer(1, 8))

    _field(story, "Grupo de Servicio", data.grupo_servicio, normal)
    _field(story, "Modalidad de servicio", data.modalidad_servicio, normal)
    _field(
        story,
        "Código Diagnóstico Principal",
        f"{data.diagnostico_codigo} - {data.diagnostico_descripcion}",
        normal,
    )
    _field(story, "Código Diagnóstico Relacionado", data.diagnostico_relacionado, normal)
    _field(story, "Origen", data.origen, normal)
    _field(story, "Causa", data.causa, normal)
    _field(story, "Incapacidad Retroactiva", data.incapacidad_retroactiva, normal)
    _field(story, "Prórroga", data.prorroga, normal)
    if data.motivo:
        _field(story, "Motivo consulta", data.motivo, normal)
    if data.sintomas:
        _field(story, "Síntomas", data.sintomas, normal)
    story.append(Spacer(1, 16))

    story.append(Paragraph(f"{data.medico_nombre}", normal))
    story.append(Paragraph(f"T. Profesional {data.registro_medico}", normal))
    story.append(Paragraph(f"Especialidad {data.medico_especialidad.upper()}", normal))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Firma del médico</b>", styles["Heading2"]))
    _append_medico_firma(story, medico)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    pdf_dir = os.path.abspath(settings.pdf_output_dir)
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"incapacidad_{historial.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    return pdf_path, data


def incapacidad_data_as_ocr_fallback(data: IncapacidadPdfData) -> dict:
    return {
        "numero_incapacidad": data.numero_incapacidad,
        "fecha_documento": data.fecha_documento,
        "paciente_nombre": data.paciente_nombre,
        "paciente_tipo_documento": data.paciente_tipo_documento,
        "paciente_numero_documento": data.paciente_numero_documento,
        "tipo_paciente": data.tipo_paciente,
        "sexo": data.sexo,
        "fecha_nacimiento": data.fecha_nacimiento,
        "edad_texto": data.edad_texto,
        "eps_detectada": data.eps_detectada,
        "entidad_codigo": data.entidad_codigo,
        "medico_nombre": data.medico_nombre,
        "registro_medico": data.registro_medico,
        "medico_especialidad": data.medico_especialidad,
        "diagnostico_codigo": data.diagnostico_codigo,
        "diagnostico_descripcion": data.diagnostico_descripcion,
        "diagnostico_relacionado": data.diagnostico_relacionado,
        "fecha_inicio": data.fecha_inicio,
        "fecha_fin": data.fecha_fin,
        "dias": data.dias,
        "grupo_servicio": data.grupo_servicio,
        "modalidad_servicio": data.modalidad_servicio,
        "origen": data.origen,
        "causa": data.causa,
        "incapacidad_retroactiva": data.incapacidad_retroactiva,
        "prorroga": data.prorroga,
    }
