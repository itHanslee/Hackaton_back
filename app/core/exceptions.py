import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.core.responses import safe_client_message

logger = logging.getLogger(__name__)


def _error_json(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": message}},
    )


def _format_validation_errors(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "body")
        msg = str(err.get("msg", "valor inválido"))
        if loc:
            parts.append(f"{loc}: {msg}")
        else:
            parts.append(msg)
    return "; ".join(parts) if parts else "Datos de entrada no válidos."


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    raw = _format_validation_errors(exc)
    message = safe_client_message(
        raw, fallback="Datos de entrada no válidos."
    )
    return _error_json("VALIDATION_ERROR", message, 422)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error_json(
        "INTERNAL_ERROR",
        safe_client_message(None, fallback="Error interno del servidor."),
        500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
