from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.db_models import EPS, Medico

router = APIRouter(prefix="/medicos", tags=["medicos"])


@router.get("")
def list_medicos(db: Session = Depends(get_db)):
    medicos = db.query(Medico).order_by(Medico.id.asc()).all()
    data = []
    for medico in medicos:
        eps = db.query(EPS).filter(EPS.id == medico.eps_id).first()
        data.append({
            "id": medico.id,
            "nombre": medico.nombre,
            "especialidad": medico.especialidad,
            "eps": eps.nombre if eps else "",
        })
    return {"data": data, "error": None}


@router.get("/{id}/slots")
def get_medico_slots(id: int, date: str | None = None):
    base_date = datetime.utcnow()
    if date:
        try:
            base_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            pass

    slots = []
    for index, hour in enumerate(range(9, 17)):
        start_time = base_date.replace(hour=hour, minute=0, second=0, microsecond=0)
        slots.append({"id": id * 100 + index + 1, "datetime": start_time.isoformat()})
    return {"data": slots, "error": None}
