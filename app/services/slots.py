from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.db_models import Cita


class SlotsService:
    def __init__(self, db: Session):
        self.db = db

    def generate_slots(self, medico_id: int, slot_date: date) -> list[dict]:
        start = datetime.combine(slot_date, time(9, 0))
        end = datetime.combine(slot_date, time(17, 0))

        day_start = datetime.combine(slot_date, time.min)
        day_end = datetime.combine(slot_date, time.max)

        booked_times = {
            self._normalize_datetime(cita.fecha_hora)
            for cita in self.db.query(Cita)
            .filter(
                Cita.medico_id == medico_id,
                Cita.fecha_hora >= day_start,
                Cita.fecha_hora <= day_end,
            )
            .all()
            if cita.fecha_hora is not None
        }

        slots: list[dict] = []
        current = start
        while current < end:
            normalized = self._normalize_datetime(current)
            iso_datetime = normalized.isoformat()
            slots.append(
                {
                    "id": f"{medico_id}_{iso_datetime}",
                    "datetime": iso_datetime,
                    "available": normalized not in booked_times,
                }
            )
            current += timedelta(minutes=30)

        return slots

    def is_slot_available(self, medico_id: int, fecha_hora: datetime) -> bool:
        normalized = self._normalize_datetime(fecha_hora)
        slots = self.generate_slots(medico_id, normalized.date())
        for slot in slots:
            if slot["datetime"] == normalized.isoformat():
                return slot["available"]
        return False

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.replace(microsecond=0)
