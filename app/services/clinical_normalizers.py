"""Normalización compartida de campos clínicos."""


def parse_sintomas(value: list | str | None) -> list[str]:
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    if not value:
        return []
    return [s.strip() for s in str(value).split(",") if s.strip()]


def sintomas_to_db(value: list | str | None) -> str:
    return ", ".join(parse_sintomas(value))
