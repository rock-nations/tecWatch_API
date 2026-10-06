import json
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from src.services.client import UpstreamConnectionError, UpstreamResponseError, UpstreamTimeoutError
from src.services.xml_handler import XMLParseError
from src.utils.logger import logger


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        formatted_errors = []
        for error in exc.errors():
            loc = " -> ".join([str(x) for x in error.get("loc", [])])
            msg = error.get("msg", "Validation error")
            err_type = error.get("type", "unknown")

            # Clarify error message for extra/unexpected fields
            if "extra_forbidden" in err_type:
                msg = f"Unexpected field '{loc}' is not permitted."
            elif "missing" in err_type:
                msg = f"Mandatory field '{loc}' is required but was not provided."
            elif "type_error" in err_type or "strict" in err_type:
                msg = f"Invalid data type for field '{loc}': {msg}"

            formatted_errors.append({
                "field": loc,
                "type": err_type,
                "message": msg,
            })

        logger.warning(f"Request validation failed on {request.url.path}: {formatted_errors}")
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation Error",
                "detail": "The request payload failed validation criteria (check mandatory fields, data types, message length, or unexpected content).",
                "validation_errors": formatted_errors,
            },
        )

    @app.exception_handler(json.decoder.JSONDecodeError)
    async def json_decode_error_handler(request: Request, exc: json.decoder.JSONDecodeError):
        logger.warning(f"Invalid JSON payload received on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid JSON",
                "detail": f"Malformed JSON syntax at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            },
        )

    @app.exception_handler(XMLParseError)
    async def xml_parse_error_handler(request: Request, exc: XMLParseError):
        logger.warning(f"Invalid XML payload received on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid XML",
                "detail": str(exc),
            },
        )

    @app.exception_handler(UpstreamConnectionError)
    async def upstream_connect_handler(request: Request, exc: UpstreamConnectionError):
        logger.error(f"Upstream connection failed: {exc}")
        return JSONResponse(
            status_code=502,
            content={
                "error": "Bad Gateway",
                "detail": str(exc),
            },
        )

    @app.exception_handler(UpstreamTimeoutError)
    async def upstream_timeout_handler(request: Request, exc: UpstreamTimeoutError):
        logger.error(f"Upstream connection timed out: {exc}")
        return JSONResponse(
            status_code=504,
            content={
                "error": "Gateway Timeout",
                "detail": str(exc),
            },
        )

    @app.exception_handler(UpstreamResponseError)
    async def upstream_response_handler(request: Request, exc: UpstreamResponseError):
        logger.error(f"Upstream returned error {exc.status_code}: {exc.detail}")
        return JSONResponse(
            status_code=502,
            content={
                "error": "Bad Gateway",
                "detail": f"Target server returned error code {exc.status_code}",
                "upstream_response": exc.detail,
            },
        )
