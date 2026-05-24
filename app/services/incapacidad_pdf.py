"""Genera PDF de incapacidad laboral desde datos de la BD (legible por OCR)."""

import os
import re
from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from app.core.config import get_settings
from app.services.historial_bundle import HistorialBundle, incapacidad_dias, incapacidad_fechas
from app.services.pdf import _append_medico_firma


@dataclass
class IncapacidadPdfData:
    numero_incapacidad: str
    paciente_nombre: str
    paciente_tipo_documento: str
    paciente_numero_documento: str
    eps_detectada: str
    medico_nombre: str
    registro_medico: str
    diagnostico_codigo: str
    diagnostico_descripcion: str
    fecha_inicio: str
    fecha_fin: str
    dias: int
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


def build_incapacidad_data(
    bundle: HistorialBundle,
    dias_override: int | None = None,
) -> IncapacidadPdfData:
    historial = bundle.historial
    paciente = bundle.paciente
    medico = bundle.medico
    eps_name = bundle.eps.nombre if bundle.eps else "EPS NO REGISTRADA"

    dias = incapacidad_dias(historial, dias_override)
    inicio, fin = incapacidad_fechas(bundle, dias)
    cie, desc = _extract_cie10(historial.diagnostico)

    return IncapacidadPdfData(
        numero_incapacidad=f"INC-{historial.id}-{inicio.year}",
        paciente_nombre=(paciente.nombre if paciente else "PACIENTE"),
        paciente_tipo_documento="CC",
        paciente_numero_documento=(paciente.cedula if paciente else ""),
        eps_detectada=eps_name,
        medico_nombre=(medico.nombre if medico else "MÉDICO TRATANTE"),
        registro_medico=(medico.cedula if medico else ""),
        diagnostico_codigo=cie,
        diagnostico_descripcion=desc,
        fecha_inicio=inicio.isoformat(),
        fecha_fin=fin.isoformat(),
        dias=dias,
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

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    title = styles["Heading1"]
    normal = styles["Normal"]
    story: list = []

    story.append(Paragraph("CERTIFICADO DE INCAPACIDAD LABORAL", title))
    story.append(Spacer(1, 12))
    if eps and eps.logo_path and os.path.isfile(eps.logo_path):
        story.append(Image(eps.logo_path, width=80, height=40))
        story.append(Spacer(1, 8))

    _field(story, "Número de incapacidad", data.numero_incapacidad, normal)
    _field(story, "EPS", data.eps_detectada, normal)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>DATOS DEL PACIENTE</b>", styles["Heading2"]))
    _field(story, "Nombre", data.paciente_nombre, normal)
    _field(story, "Tipo documento", data.paciente_tipo_documento, normal)
    _field(story, "Número documento", data.paciente_numero_documento, normal)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>DATOS DEL MÉDICO</b>", styles["Heading2"]))
    _field(story, "Nombre médico", data.medico_nombre, normal)
    _field(story, "Registro médico", data.registro_medico, normal)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>INCAPACIDAD</b>", styles["Heading2"]))
    _field(story, "Fecha inicio", data.fecha_inicio, normal)
    _field(story, "Fecha fin", data.fecha_fin, normal)
    _field(story, "Días", str(data.dias), normal)
    _field(story, "Diagnóstico CIE-10", data.diagnostico_codigo, normal)
    _field(story, "Descripción diagnóstico", data.diagnostico_descripcion, normal)
    _field(story, "Motivo consulta", data.motivo, normal)
    _field(story, "Síntomas", data.sintomas, normal)
    story.append(Spacer(1, 16))

    story.append(Paragraph("<b>Firma del médico</b>", styles["Heading2"]))
    _append_medico_firma(story, medico)
    if medico:
        story.append(Paragraph(f"Dr(a). {medico.nombre} — Reg. {medico.cedula}", normal))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    settings = get_settings()
    pdf_dir = os.path.abspath(settings.pdf_output_dir)
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"incapacidad_{historial.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    return pdf_path, data


def incapacidad_data_as_ocr_fallback(data: IncapacidadPdfData) -> dict:
    return {
        "numero_incapacidad": data.numero_incapacidad,
        "paciente_nombre": data.paciente_nombre,
        "paciente_tipo_documento": data.paciente_tipo_documento,
        "paciente_numero_documento": data.paciente_numero_documento,
        "eps_detectada": data.eps_detectada,
        "medico_nombre": data.medico_nombre,
        "registro_medico": data.registro_medico,
        "diagnostico_codigo": data.diagnostico_codigo,
        "diagnostico_descripcion": data.diagnostico_descripcion,
        "fecha_inicio": data.fecha_inicio,
        "fecha_fin": data.fecha_fin,
        "dias": data.dias,
    }
