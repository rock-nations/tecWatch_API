import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from config.settings import ConfigManager
from src.models.analysis import AnalysisReport, AnalysisResultResponse
from src.models.scenarios import AnalysisScenarios
from src.models.status import StatusResponse
from src.services.analysis_report import load_analysis_report, load_analysis_scenarios
from src.services.client import TecWatchClient, UpstreamDataError
from src.services.xml_handler import XMLParseError, dict_to_xml_str, parse_xml_to_dict
from src.utils.logger import logger

router = APIRouter()


def get_client() -> TecWatchClient:
    return TecWatchClient()


@router.get(
    "/status",
    summary="Fetch tecWatch status information",
    responses={
        200: {"model": StatusResponse, "description": "Validated tecWatch status of the monitored SCI-TDS interface"},
        502: {"description": "tecWatch server unreachable, returned an error, or sent a status that fails validation"},
        504: {"description": "tecWatch server timed out"},
    },
)
async def get_status(
    request: Request,
    device_id: Optional[str] = Query(None, min_length=1, max_length=64, description="Optional Device ID"),
    client: TecWatchClient = Depends(get_client),
):
    """
    Retrieves current status information from the configured tecWatch server.
    Supports both JSON and XML responses based on the HTTP Accept header.
    """
    raw_status = await client.fetch_status(device_id=device_id)

    # Validate against strict StatusResponse schema
    try:
        validated_status = StatusResponse.model_validate(raw_status)
    except ValidationError as val_err:
        raise UpstreamDataError(
            "tecWatch status response failed validation (check mandatory fields, data types, or unexpected content).",
            val_err.errors(),
        )

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        status_dict = validated_status.model_dump(mode="json")
        xml_output = dict_to_xml_str("tecWatchStatus", status_dict)
        return Response(content=xml_output, media_type="application/xml")

    return validated_status


@router.get(
    "/analysis",
    summary="Fetch the validated post-analysis report for the Web GUI",
    responses={
        200: {"model": AnalysisReport, "description": "The analysis report exactly as stored in the report file"},
        404: {"description": "The configured analysis report file does not exist"},
        500: {"description": "The analysis report is too large, malformed, or fails schema validation"},
    },
)
async def get_analysis(request: Request):
    """
    Reads the configured analysis report JSON file, validates it (message length, message format,
    mandatory fields, data types, unexpected content) and returns it unchanged.
    The file is read on every request, so a regenerated report is served without a restart.
    """
    analysis_cfg = ConfigManager.get_instance().config.analysis
    report = await run_in_threadpool(
        load_analysis_report, analysis_cfg.resolved_report_path, analysis_cfg.max_report_bytes
    )

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        xml_output = dict_to_xml_str("AnalysisReport", report)
        return Response(content=xml_output, media_type="application/xml")

    return report


@router.get(
    "/analysis/scenarios",
    summary="Fetch the validated failure-analysis scenarios (findings) for the Web GUI",
    responses={
        200: {"model": AnalysisScenarios, "description": "The analysis scenarios exactly as stored in the scenarios file"},
        404: {"description": "The configured analysis scenarios file does not exist"},
        500: {"description": "The analysis scenarios file is too large, malformed, or fails schema validation"},
    },
)
async def get_analysis_scenarios(request: Request):
    """
    Reads the configured analysis scenarios JSON file (extracted from the data-analysis workbook with
    scripts/extract_analysis_scenarios.py), validates it and returns it unchanged.
    The file is read on every request, so a regenerated file is served without a restart.
    """
    analysis_cfg = ConfigManager.get_instance().config.analysis
    scenarios = await run_in_threadpool(
        load_analysis_scenarios, analysis_cfg.resolved_scenarios_path, analysis_cfg.max_report_bytes
    )

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        xml_output = dict_to_xml_str("AnalysisScenarios", scenarios)
        return Response(content=xml_output, media_type="application/xml")

    return scenarios


@router.post("/analysis", summary="Send post-analysis results to DBLTAS")
async def post_analysis(
    request: Request,
    client: TecWatchClient = Depends(get_client),
):
    """
    Accepts post-analysis results in JSON or XML format, structured like the analysis report.
    Validates message length, mandatory fields, data types, and rejects unexpected content.
    Forwards validated data to the configured target server.
    """
    content_type = request.headers.get("content-type", "").lower()
    raw_body = await request.body()

    if not raw_body:
        raise HTTPException(
            status_code=400,
            detail="Request body cannot be empty. Mandatory analysis fields required.",
        )

    data_to_validate = None
    validation_options = {}

    if "application/json" in content_type:
        try:
            data_to_validate = json.loads(raw_body)
        except json.decoder.JSONDecodeError as exc:
            raise exc
        if not isinstance(data_to_validate, dict):
            raise HTTPException(
                status_code=422,
                detail="Payload must be a JSON object containing analysis result fields.",
            )

    elif "application/xml" in content_type or "text/xml" in content_type:
        try:
            parsed = parse_xml_to_dict(raw_body)
            # Unwrap root tag if present (e.g. <AnalysisResult>...</AnalysisResult>)
            if len(parsed) == 1:
                root_tag = next(iter(parsed.keys()))
                data_to_validate = parsed[root_tag]
            else:
                data_to_validate = parsed
        except XMLParseError as exc:
            raise exc
        # XML values are untyped text, so numbers and timestamps are converted instead of strictly checked
        validation_options = {"strict": False, "context": {"source_format": "xml"}}

    else:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported Content-Type '{content_type}'. Must be 'application/json' or 'application/xml'.",
        )

    # Validate against strict Pydantic model (rejects missing fields, invalid types, extra fields)
    try:
        validated_request = AnalysisReport.model_validate(data_to_validate, **validation_options)
    except ValidationError as val_err:
        from fastapi.exceptions import RequestValidationError
        raise RequestValidationError(val_err.errors())

    # Forward to configured target server
    upstream_payload = validated_request.model_dump(mode="json")
    await client.send_analysis_result(upstream_payload)

    # Construct acknowledgment response
    res = AnalysisResultResponse(
        status="SUCCESS",
        message="Post-analysis result validated and sent to target server",
        analysis_id=validated_request.analysis_id,
        processed_at=datetime.now(timezone.utc),
    )

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        res_dict = res.model_dump(mode="json")
        xml_output = dict_to_xml_str("AnalysisResultResponse", res_dict)
        return Response(content=xml_output, media_type="application/xml")

    return res


@router.get("/config", summary="Inspect current active configuration")
async def get_active_config():
    """Inspect the currently loaded server and API configuration."""
    cfg = ConfigManager.get_instance().config
    return {
        "server": {
            "host": cfg.server.host,
            "port": cfg.server.port,
            "base_url": cfg.server.base_url,
            "timeout_seconds": cfg.server.timeout_seconds,
        },
        "api": {
            "status_endpoint": cfg.api.status_endpoint,
            "result_endpoint": cfg.api.result_endpoint,
            "max_payload_bytes": cfg.api.max_payload_bytes,
        },
        "analysis": {
            "report_path": cfg.analysis.report_path,
            "resolved_report_path": str(cfg.analysis.resolved_report_path),
            "scenarios_path": cfg.analysis.scenarios_path,
            "resolved_scenarios_path": str(cfg.analysis.resolved_scenarios_path),
            "max_report_bytes": cfg.analysis.max_report_bytes,
        },
        "gateway": {
            "listen_host": cfg.gateway.listen_host,
            "listen_port": cfg.gateway.listen_port,
            "log_level": cfg.gateway.log_level,
        },
    }


@router.post("/config/reload", summary="Reload configuration dynamically without server restart")
async def reload_active_config():
    """Reloads configuration values from disk and environment variables at runtime."""
    new_cfg = ConfigManager.get_instance().reload()
    logger.info(f"Configuration reloaded: target server is now {new_cfg.server.base_url}")
    return {
        "status": "SUCCESS",
        "message": f"Configuration reloaded. Connected to {new_cfg.server.base_url}",
        "new_target": new_cfg.server.base_url,
    }
