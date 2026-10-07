import json
from typing import Any, Dict, Iterable, List
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from src.services.analysis_report import AnalysisReportError
from src.services.client import (
    UpstreamConnectionError,
    UpstreamDataError,
    UpstreamResponseError,
    UpstreamTimeoutError,
)
from src.services.upload_analysis import UploadAnalysisError
from src.services.xml_handler import XMLParseError
from src.utils.logger import logger


def format_validation_errors(errors: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Converts pydantic validation errors into the standardized field/type/message entries."""
    formatted_errors = []
    for error in errors:
        loc = " -> ".join([str(x) for x in error.get("loc", [])])
        msg = error.get("msg", "Validation error")
        err_type = error.get("type", "unknown")

        # Clarify error message for extra/unexpected fields
        if "extra_forbidden" in err_type:
            msg = f"Unexpected field '{loc}' is not permitted."
        elif "missing" in err_type:
            msg = f"Mandatory field '{loc}' is required but was not provided."
        elif err_type.endswith("_type"):
            msg = f"Invalid data type for field '{loc}': {msg}"

        formatted_errors.append({
            "field": loc,
            "type": err_type,
            "message": msg,
        })
    return formatted_errors


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        formatted_errors = format_validation_errors(exc.errors())

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

    @app.exception_handler(AnalysisReportError)
    async def analysis_report_error_handler(request: Request, exc: AnalysisReportError):
        content = {
            "error": exc.error,
            "detail": exc.detail,
        }
        if exc.validation_errors:
            content["validation_errors"] = format_validation_errors(exc.validation_errors)

        logger.error(f"Analysis report rejected on {request.url.path}: {content}")
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(UploadAnalysisError)
    async def upload_analysis_error_handler(request: Request, exc: UploadAnalysisError):
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(f"Upload rejected on {request.url.path}: {exc.error} - {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error,
                "detail": exc.detail,
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

    @app.exception_handler(UpstreamDataError)
    async def upstream_data_handler(request: Request, exc: UpstreamDataError):
        formatted_errors = format_validation_errors(exc.validation_errors)
        logger.error(f"Upstream data rejected on {request.url.path}: {formatted_errors}")
        return JSONResponse(
            status_code=502,
            content={
                "error": "Bad Gateway",
                "detail": exc.detail,
                "validation_errors": formatted_errors,
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
