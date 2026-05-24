"""Validación de imágenes (firma médico, logo EPS)."""

from app.core.config import get_settings

ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
    }
)

EXTENSION_BY_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


class ImageValidationError(ValueError):
    """Raised when image payload fails validation."""


def _detect_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes, mime_type: str | None = None, *, max_mb: int | None = None) -> str:
    if not data:
        raise ImageValidationError("Imagen vacía.")

    settings = get_settings()
    limit_mb = max_mb if max_mb is not None else settings.max_image_mb
    max_bytes = limit_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ImageValidationError(f"La imagen supera el límite de {limit_mb} MB.")

    detected = _detect_mime(data)
    if not detected:
        raise ImageValidationError("Formato de imagen no reconocido. Use PNG, JPEG o WebP.")

    declared = (mime_type or "").lower().split(";")[0].strip()
    if declared and declared not in ALLOWED_IMAGE_MIMES:
        raise ImageValidationError(f"Tipo de imagen no permitido: {declared}.")

    if declared in ALLOWED_IMAGE_MIMES and declared.replace("jpg", "jpeg") != detected.replace("jpg", "jpeg"):
        if not (declared in {"image/jpeg", "image/jpg"} and detected == "image/jpeg"):
            raise ImageValidationError("El contenido no coincide con el tipo declarado.")

    return EXTENSION_BY_MIME.get(detected, ".png")
