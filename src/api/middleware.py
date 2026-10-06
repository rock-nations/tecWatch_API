import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from config.settings import ConfigManager
from src.utils.logger import logger


class MessageLengthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces payload message-length limits.
    Inspects Content-Length header and streamed byte length, rejecting oversized
    payloads with HTTP 413 Payload Too Large before allocating memory.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        max_bytes = ConfigManager.get_instance().config.api.max_payload_bytes
        content_length_header = request.headers.get("content-length")

        if content_length_header:
            try:
                content_length = int(content_length_header)
                if content_length > max_bytes:
                    logger.warning(
                        f"Payload too large: Content-Length {content_length} exceeds limit of {max_bytes} bytes."
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Payload Too Large",
                            "detail": f"Request body size ({content_length} bytes) exceeds configured limit ({max_bytes} bytes).",
                            "limit_bytes": max_bytes,
                            "received_bytes": content_length,
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Bad Request",
                        "detail": "Invalid Content-Length header format.",
                    },
                )

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs incoming HTTP requests and their processing duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"
        logger.info(f"Incoming {request.method} {request.url.path} from {client_host}")

        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Completed {request.method} {request.url.path} -> HTTP {response.status_code} ({duration_ms:.2f}ms)"
        )
        return response
