"""Map DB models to shapes expected by the React frontend."""

from sqlalchemy.orm import Session

from app.models.db_models import Cita, Consulta, EPS, Historial, Medico, Paciente


def _eps_name(eps: EPS | None) -> str:
    return eps.nombre if eps else ""


def _parse_sintomas(value: str | list | None) -> list[str]:
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    if not value:
        return []
    return [s.strip() for s in str(value).split(",") if s.strip()]


def _medicamentos_to_frontend(payload: dict | None) -> list[dict]:
    if not payload:
        return []

    if isinstance(payload, list):
        return payload

    result: list[dict] = []
    for item in payload.get("disponibles_eps") or []:
        if isinstance(item, dict):
            result.append(
                {
                    "nombre": item.get("nombre", ""),
                    "cubierto": True,
                    "generico_alternativa": item.get("nombre_generico")
                    or item.get("descripcion")
                    or item.get("dosis", ""),
                    "dosis": item.get("dosis"),
                    "frecuencia": item.get("frecuencia"),
                }
            )
        elif isinstance(item, str):
            result.append({"nombre": item, "cubierto": True})

    for item in payload.get("ideales_sugeridos") or []:
        if isinstance(item, dict):
            result.append(
                {
                    "nombre": item.get("nombre", ""),
                    "cubierto": False,
                    "generico_alternativa": item.get("razon")
                    or item.get("nombre_generico")
                    or item.get("descripcion", ""),
                }
            )

    for item in payload.get("items") or []:
        if isinstance(item, dict) and item.get("nombre"):
            result.append(item)

    return result


def _frontend_medicamentos_to_db(medicamentos: list | dict | None, extra: dict | None = None) -> dict:
    payload = dict(extra or {})
    if isinstance(medicamentos, list):
        payload["items"] = medicamentos
    elif isinstance(medicamentos, dict):
        payload.update(medicamentos)
    return payload


def historial_to_frontend(
    historial: Historial,
    *,
    paciente: Paciente | None = None,
    eps: EPS | None = None,
) -> dict:
    meds_payload = historial.medicamentos_sugeridos or {}
    if paciente is None and historial.consulta and historial.consulta.cita:
        paciente = historial.consulta.cita.paciente
    if eps is None and paciente and paciente.eps:
        eps = paciente.eps

    return {
        "id": historial.id,
        "motivo": historial.motivo_consulta or "",
        "sintomas": _parse_sintomas(historial.sintomas),
        "diagnostico": historial.diagnostico or "",
        "plan": historial.plan_tratamiento or "",
        "alergias": meds_payload.get("alergias", ""),
        "notas_adicionales": meds_payload.get("notas_adicionales", ""),
        "medicamentos": _medicamentos_to_frontend(meds_payload),
        "firmado": bool(historial.confirmado_por_medico),
        "paciente_eps": _eps_name(eps),
        "paciente_nombre": paciente.nombre if paciente else "",
        "paciente_documento": paciente.cedula if paciente else "",
        "paciente_telefono": paciente.telefono if paciente else "",
        "paciente_fecha_nacimiento": paciente.fecha_nacimiento if paciente else "",
        "incapacidad_dias": meds_payload.get("incapacidad_dias"),
        "incapacidad_recomendaciones": meds_payload.get("incapacidad_recomendaciones"),
    }


def apply_frontend_historial(historial: Historial, body: dict) -> None:
    if "motivo_consulta" in body:
        historial.motivo_consulta = body.get("motivo_consulta") or ""
    if "plan_tratamiento" in body:
        historial.plan_tratamiento = body.get("plan_tratamiento") or ""
    if "motivo" in body:
        historial.motivo_consulta = body.get("motivo") or ""
    if "diagnostico" in body:
        historial.diagnostico = body.get("diagnostico") or ""
    if "plan" in body:
        historial.plan_tratamiento = body.get("plan") or ""
    if "sintomas" in body:
        historial.sintomas = ", ".join(_parse_sintomas(body.get("sintomas")))

    extra = dict(historial.medicamentos_sugeridos or {})
    if "alergias" in body:
        extra["alergias"] = body.get("alergias") or ""
    if "notas_adicionales" in body:
        extra["notas_adicionales"] = body.get("notas_adicionales") or ""
    if "incapacidad_dias" in body:
        extra["incapacidad_dias"] = body.get("incapacidad_dias")
        if body.get("incapacidad_dias"):
            extra["requiere_incapacidad"] = True
    if "requiere_incapacidad" in body:
        extra["requiere_incapacidad"] = bool(body.get("requiere_incapacidad"))
    if "incapacidad_recomendaciones" in body:
        extra["incapacidad_recomendaciones"] = body.get("incapacidad_recomendaciones")
    if "medicamentos" in body:
        extra = _frontend_medicamentos_to_db(body.get("medicamentos"), extra)
    historial.medicamentos_sugeridos = extra


def cita_to_calendario(db: Session, cita: Cita) -> dict:
    paciente = cita.paciente or db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
    medico = cita.medico or db.query(Medico).filter(Medico.id == cita.medico_id).first()
    eps = paciente.eps if paciente and paciente.eps else None

    historial_id = None
    consulta = (
        db.query(Consulta)
        .filter(Consulta.cita_id == cita.id)
        .order_by(Consulta.id.desc())
        .first()
    )
    if consulta:
        historial_row = (
            db.query(Historial.id)
            .filter(Historial.consulta_id == consulta.id)
            .order_by(Historial.id.desc())
            .first()
        )
        if historial_row:
            historial_id = historial_row[0]

    estado = cita.estado or "pendiente"
    if estado == "pendiente":
        estado = "programada"

    return {
        "id": str(cita.id),
        "paciente_id": str(cita.paciente_id),
        "paciente_nombre": paciente.nombre if paciente else "",
        "paciente_documento": paciente.cedula if paciente else "",
        "paciente_eps": _eps_name(eps),
        "medico_id": cita.medico_id,
        "medico_nombre": medico.nombre if medico else "",
        "especialidad": medico.especialidad if medico else "",
        "fecha_hora": cita.fecha_hora.isoformat() if cita.fecha_hora else "",
        "estado": estado,
        "motivo": cita.motivo,
        "historial_id": historial_id,
    }


def cita_to_activa(db: Session, cita: Cita) -> dict:
    row = cita_to_calendario(db, cita)
    return {
        "id": row["id"],
        "paciente_id": row["paciente_id"],
        "paciente_nombre": row["paciente_nombre"],
        "medico_nombre": row["medico_nombre"],
        "especialidad": row["especialidad"],
        "fecha_hora": row["fecha_hora"],
        "estado": row["estado"],
    }


def paciente_resumen(db: Session, paciente: Paciente, medico_id: int | None = None) -> dict:
    citas_q = db.query(Cita).filter(Cita.paciente_id == paciente.id)
    if medico_id is not None:
        citas_q = citas_q.filter(Cita.medico_id == medico_id)
    citas = citas_q.all()
    cita_ids = [c.id for c in citas]

    consultas_q = db.query(Consulta).filter(Consulta.cita_id.in_(cita_ids)) if cita_ids else None
    consultas = consultas_q.all() if consultas_q is not None else []
    consulta_ids = [c.id for c in consultas]

    historiales_q = (
        db.query(Historial).filter(Historial.consulta_id.in_(consulta_ids))
        if consulta_ids
        else None
    )
    historiales = historiales_q.all() if historiales_q is not None else []

    ultima = ""
    if historiales:
        latest = max(historiales, key=lambda h: h.created_at or h.id)
        ultima = latest.created_at.isoformat() if latest.created_at else ""
    elif citas:
        latest_cita = max(citas, key=lambda c: c.fecha_hora or c.id)
        ultima = latest_cita.fecha_hora.isoformat() if latest_cita.fecha_hora else ""

    return {
        "id": str(paciente.id),
        "nombre": paciente.nombre,
        "documento": paciente.cedula,
        "eps": _eps_name(paciente.eps),
        "telefono": paciente.telefono,
        "ultima_consulta": ultima,
        "total_consultas": len(historiales) or len(consultas),
    }


def paciente_detalle(db: Session, paciente: Paciente, medico_id: int | None = None) -> dict:
    base = paciente_resumen(db, paciente, medico_id)
    citas_q = db.query(Cita).filter(Cita.paciente_id == paciente.id)
    if medico_id is not None:
        citas_q = citas_q.filter(Cita.medico_id == medico_id)
    citas = citas_q.order_by(Cita.fecha_hora.desc()).all()

    consultas: list[dict] = []
    for cita in citas:
        consulta = (
            db.query(Consulta)
            .filter(Consulta.cita_id == cita.id)
            .order_by(Consulta.id.desc())
            .first()
        )
        if not consulta:
            continue
        historial = (
            db.query(Historial)
            .filter(Historial.consulta_id == consulta.id)
            .order_by(Historial.id.desc())
            .first()
        )
        medico = cita.medico or db.query(Medico).filter(Medico.id == cita.medico_id).first()
        consultas.append(
            {
                "id": consulta.id,
                "historial_id": historial.id if historial else consulta.id,
                "fecha": consulta.created_at.isoformat() if consulta.created_at else cita.fecha_hora.isoformat(),
                "diagnostico": historial.diagnostico if historial else "Consulta registrada",
                "medico_nombre": medico.nombre if medico else "",
                "estado": cita.estado or "terminada",
            }
        )

    return {**base, "consultas": consultas}
