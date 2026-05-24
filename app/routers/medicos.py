import os
from datetime import date as date_type, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.deps import require_medico
from app.core.images import ImageValidationError, validate_image
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, EPS, Medico
from app.models.schemas import EPSResponse, MedicoCitaCalendarItem, MedicoProfileResponse, MedicoResponse

router = APIRouter(prefix="/medicos", tags=["medicos"])


def _medico_has_firma(medico: Medico) -> bool:
    if medico.firma_imagen:
        return True
    return bool(medico.firma_path and os.path.isfile(medico.firma_path))


def _serialize_medico(m: Medico) -> dict:
    data = MedicoResponse.model_validate(m).model_dump()
    data["tiene_firma"] = _medico_has_firma(m)
    if m.eps:
        data["eps"] = m.eps.nombre
    return data


def _save_signature_file(medico_id: int, data: bytes, ext: str) -> str:
    settings = get_settings()
    sig_dir = Path(settings.signatures_output_dir)
    sig_dir.mkdir(parents=True, exist_ok=True)
    path = sig_dir / f"medico_{medico_id}{ext}"
    path.write_bytes(data)
    return str(path.resolve())


def _remove_file(path: str | None) -> None:
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _parse_date_param(value: str) -> date_type | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _month_bounds(month: str) -> tuple[datetime, datetime] | None:
    try:
        year, mon = map(int, month.split("-"))
        start = datetime(year, mon, 1)
        if mon == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, mon + 1, 1)
        return start, end - timedelta(microseconds=1)
    except (ValueError, TypeError):
        return None


def _serialize_medico_cita(cita: Cita) -> dict:
    paciente = cita.paciente
    return MedicoCitaCalendarItem(
        id=cita.id,
        paciente_id=cita.paciente_id,
        medico_id=cita.medico_id,
        fecha_hora=cita.fecha_hora.isoformat() if cita.fecha_hora else "",
        motivo=cita.motivo,
        estado=cita.estado,
        paciente_nombre=paciente.nombre if paciente else "—",
        paciente_cedula=paciente.cedula if paciente else "—",
    ).model_dump()


@router.get("")
def list_medicos(db: Session = Depends(get_db)):
    medicos = db.query(Medico).all()
    return ok([_serialize_medico(m) for m in medicos])


@router.get("/me")
def get_my_profile(request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not medico:
        return error_response("NOT_FOUND", "Médico no encontrado.", 404)

    tiene_firma = _medico_has_firma(medico)
    return ok(
        MedicoProfileResponse(
            id=medico.id,
            cedula=medico.cedula,
            nombre=medico.nombre,
            especialidad=medico.especialidad,
            eps_id=medico.eps_id,
            email=medico.email,
            tiene_firma=tiene_firma,
            firma_url="/medicos/me/firma" if tiene_firma else None,
        ).model_dump()
    )


@router.get("/me/citas")
def get_my_citas(
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = Query(default=None, description="Día específico (YYYY-MM-DD)"),
    month: str | None = Query(default=None, description="Mes completo (YYYY-MM)"),
):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    query = (
        db.query(Cita)
        .options(joinedload(Cita.paciente))
        .filter(Cita.medico_id == medico_id)
    )

    period_label = "all"
    if date:
        day = _parse_date_param(date)
        if day is None:
            return error_response(
                "INVALID_DATE",
                "Formato de date inválido. Use YYYY-MM-DD.",
                400,
            )
        start = datetime.combine(day, datetime.min.time())
        end = datetime.combine(day, datetime.max.time())
        query = query.filter(Cita.fecha_hora >= start, Cita.fecha_hora <= end)
        period_label = date
    elif month:
        bounds = _month_bounds(month)
        if bounds is None:
            return error_response(
                "INVALID_MONTH",
                "Formato de month inválido. Use YYYY-MM.",
                400,
            )
        start, end = bounds
        query = query.filter(Cita.fecha_hora >= start, Cita.fecha_hora <= end)
        period_label = month
    else:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(Cita.fecha_hora >= today - timedelta(days=7))

    citas = query.order_by(Cita.fecha_hora.asc()).all()
    return ok({
        "period": period_label,
        "total": len(citas),
        "items": [_serialize_medico_cita(c) for c in citas],
    })


@router.post("/me/firma")
async def upload_my_signature(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo el médico autenticado puede subir su firma.", 403)
    _, medico_id = auth

    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not medico:
        return error_response("NOT_FOUND", "Médico no encontrado.", 404)

    data = await file.read()
    settings = get_settings()
    try:
        ext = validate_image(
            data,
            file.content_type,
            max_mb=settings.max_signature_mb,
        )
    except ImageValidationError as exc:
        return error_response("INVALID_IMAGE", str(exc), 400)

    _remove_file(medico.firma_path)
    medico.firma_path = _save_signature_file(medico_id, data, ext)
    medico.firma_imagen = data
    db.commit()

    return ok(
        {
            "firma_url": "/medicos/me/firma",
            "medico_id": medico_id,
            "message": "Firma guardada. Solo usted puede usar esta firma en sus historiales.",
        }
    )


@router.get("/me/firma")
def get_my_signature(request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo el médico autenticado puede ver su firma.", 403)
    _, medico_id = auth

    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not medico or not _medico_has_firma(medico):
        return error_response("NOT_FOUND", "No tiene firma cargada.", 404)

    if medico.firma_imagen:
        media = "image/png"
        if medico.firma_path:
            lower = medico.firma_path.lower()
            if lower.endswith(".jpg") or lower.endswith(".jpeg"):
                media = "image/jpeg"
            elif lower.endswith(".webp"):
                media = "image/webp"
        return Response(content=medico.firma_imagen, media_type=media)

    media = "image/png"
    if medico.firma_path.lower().endswith(".jpg"):
        media = "image/jpeg"
    elif medico.firma_path.lower().endswith(".webp"):
        media = "image/webp"

    return FileResponse(medico.firma_path, media_type=media, filename=f"firma_medico_{medico_id}")


@router.delete("/me/firma")
def delete_my_signature(request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo el médico autenticado puede eliminar su firma.", 403)
    _, medico_id = auth

    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not medico:
        return error_response("NOT_FOUND", "Médico no encontrado.", 404)

    _remove_file(medico.firma_path)
    medico.firma_path = None
    medico.firma_imagen = None
    db.commit()
    return ok({"deleted": True})


@router.get("/{id}/slots")
def get_medico_slots(
    id: int,
    date: str | None = None,
    db: Session = Depends(get_db),
):
    from datetime import date as date_type, datetime

    from app.services.slots import SlotsService

    slot_date: date_type
    if date:
        try:
            slot_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return error_response(
                "INVALID_DATE",
                "Formato de fecha inválido. Use YYYY-MM-DD.",
                400,
            )
    else:
        slot_date = datetime.utcnow().date()

    medico = db.query(Medico).filter(Medico.id == id).first()
    if not medico:
        return error_response("NOT_FOUND", "Médico no encontrado", 404)

    slots = SlotsService(db).generate_slots(id, slot_date)
    return ok({"slots": slots})
