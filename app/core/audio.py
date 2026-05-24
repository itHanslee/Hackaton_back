import base64
import binascii
import re

from app.core.config import get_settings

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "audio/webm",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
    }
)

_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,", re.IGNORECASE)


class AudioValidationError(ValueError):
    """Raised when audio payload fails validation."""


def decode_base64_audio(data: str, *, validate: bool = True) -> bytes:
    if not data or not isinstance(data, str):
        raise AudioValidationError("Audio vacío o inválido.")

    payload = data.strip()
    match = _DATA_URL_RE.match(payload)
    if match:
        mime = match.group(1).lower()
        if validate and mime not in ALLOWED_MIME_TYPES:
            raise AudioValidationError(f"Tipo de audio no permitido: {mime}.")
        payload = payload[match.end() :]

    try:
        raw = base64.b64decode(payload, validate=validate)
    except (binascii.Error, ValueError) as exc:
        raise AudioValidationError("Codificación base64 inválida.") from exc

    if not raw:
        raise AudioValidationError("Audio vacío.")

    if validate:
        check_audio_size(raw)

    return raw


def check_audio_size(data: bytes, *, max_mb: int | None = None) -> None:
    settings = get_settings()
    limit_mb = max_mb if max_mb is not None else settings.max_audio_mb
    max_bytes = limit_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise AudioValidationError(
            f"El audio supera el límite de {limit_mb} MB."
        )
