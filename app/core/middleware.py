import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP rate limiter (requests per minute)."""

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        settings = get_settings()
        limit = settings.rate_limit_per_minute
        now = time.time()
        window_start = now - 60.0
        ip = self._client_ip(request)

        recent = [t for t in self._hits[ip] if t > window_start]
        if len(recent) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "data": None,
                    "error": {
                        "code": "RATE_LIMIT",
                        "message": "Demasiadas solicitudes. Intente más tarde.",
                    },
                },
            )

        recent.append(now)
        self._hits[ip] = recent
        return await call_next(request)
