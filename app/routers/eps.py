import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import require_medico
from app.core.images import ImageValidationError, validate_image
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import EPS, Medico
from app.models.schemas import EPSResponse

router = APIRouter(prefix="/eps", tags=["eps"])


def _serialize_eps(eps: EPS) -> dict:
    data = EPSResponse.model_validate(eps).model_dump()
    data["tiene_logo"] = bool(eps.logo_path and os.path.isfile(eps.logo_path))
    data["logo_url"] = f"/eps/{eps.id}/logo" if data["tiene_logo"] else None
    return data


def _save_logo_file(eps_id: int, data: bytes, ext: str) -> str:
    settings = get_settings()
    logo_dir = Path(settings.logos_output_dir)
    logo_dir.mkdir(parents=True, exist_ok=True)
    path = logo_dir / f"eps_{eps_id}{ext}"
    path.write_bytes(data)
    return str(path.resolve())


def _remove_file(path: str | None) -> None:
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


@router.get("")
def list_eps(db: Session = Depends(get_db)):
    rows = db.query(EPS).order_by(EPS.nombre).all()
    return ok([_serialize_eps(e) for e in rows])


@router.get("/{id}/logo")
def get_eps_logo(id: int, db: Session = Depends(get_db)):
    eps = db.query(EPS).filter(EPS.id == id).first()
    if not eps or not eps.logo_path or not os.path.isfile(eps.logo_path):
        return error_response("NOT_FOUND", "Logo no encontrado.", 404)

    media = "image/png"
    if eps.logo_path.lower().endswith(".jpg"):
        media = "image/jpeg"
    elif eps.logo_path.lower().endswith(".webp"):
        media = "image/webp"

    return FileResponse(eps.logo_path, media_type=media, filename=f"logo_eps_{id}")


@router.post("/{id}/logo")
async def upload_eps_logo(
    id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados pueden subir logos EPS.", 403)
    _, medico_id = auth

    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not medico:
        return error_response("NOT_FOUND", "Médico no encontrado.", 404)
    if medico.eps_id != id:
        return error_response(
            "FORBIDDEN",
            "Solo puede subir el logo de su propia EPS.",
            403,
        )

    eps = db.query(EPS).filter(EPS.id == id).first()
    if not eps:
        return error_response("NOT_FOUND", "EPS no encontrada.", 404)

    data = await file.read()
    settings = get_settings()
    try:
        ext = validate_image(data, file.content_type, max_mb=settings.max_image_mb)
    except ImageValidationError as exc:
        return error_response("INVALID_IMAGE", str(exc), 400)

    _remove_file(eps.logo_path)
    eps.logo_path = _save_logo_file(id, data, ext)
    db.commit()

    return ok(
        {
            "eps_id": id,
            "logo_url": f"/eps/{id}/logo",
            "message": "Logo EPS guardado.",
        }
    )
