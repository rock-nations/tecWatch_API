import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from config.settings import AppConfig, ConfigManager
from src.models.analysis import (
    AnalysisResultRequest,
    AnalysisResultResponse,
    DataComparison,
    FailureFinding,
    TraceMessage,
)
from src.models.status import StatusResponse
from src.services.client import TecWatchClient
from src.services.xml_handler import XMLParseError, dict_to_xml_str, parse_xml_to_dict
from src.utils.logger import logger

router = APIRouter()

# In-memory store for analysis results accessible by the Web GUI
_analysis_store: Dict[str, AnalysisResultRequest] = {}


def _seed_initial_trace_data():
    """Seeds initial trace-analysis data matching frontend test cases."""
    if _analysis_store:
        return
    seed_item = AnalysisResultRequest(
        analysis_id="TRACE-RUN-1001",
        device_id="TW-NODE-01",
        timestamp=datetime.now(timezone.utc),
        analysis_type="TRACE_COMMUNICATION",
        result_status="FAILED",
        summary="Message length error detected on CAN bus packet ID 127.",
        trace_messages=[
            TraceMessage(
                timestamp=datetime.now(timezone.utc),
                sender="ECU_ENGINE",
                receiver="TECWATCH_RECORDER",
                protocol="CAN",
                message_type="TELEMETRY",
                status="FAILED",
                error_reason="Message Length Error",
            ),
            TraceMessage(
                timestamp=datetime.now(timezone.utc),
                sender="SENSOR_BRAKE",
                receiver="TECWATCH_RECORDER",
                protocol="CAN",
                message_type="HEARTBEAT",
                status="OK",
                error_reason=None,
            ),
        ],
        failure_findings=[
            FailureFinding(
                message_id="127",
                expected_length=64,
                actual_length=60,
                result="Message Length Error",
            ),
        ],
        data_comparisons=[
            DataComparison(field="MessageID", expected="1001", actual="1001", result="OK"),
            DataComparison(field="Length", expected="64", actual="60", result="Error"),
            DataComparison(field="Status", expected="READY", actual="READY", result="OK"),
        ],
    )
    _analysis_store[seed_item.analysis_id] = seed_item


_seed_initial_trace_data()


def get_client() -> TecWatchClient:
    return TecWatchClient()


@router.get("/status", summary="Fetch tecWatch status information")
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
    validated_status = StatusResponse(**raw_status)

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        status_dict = validated_status.model_dump(mode="json")
        xml_output = dict_to_xml_str("tecWatchStatus", status_dict)
        return Response(content=xml_output, media_type="application/xml")

    return validated_status


@router.get("/analysis", summary="List and filter trace-analysis results for Web GUI Dashboard")
async def list_analyses(
    request: Request,
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    result_status: Optional[str] = Query(None, description="Filter by outcome status (e.g. PASSED, FAILED)"),
    protocol: Optional[str] = Query(None, description="Filter by protocol (e.g. CAN, TCP)"),
    search: Optional[str] = Query(None, description="Search keyword in summary or error reasons"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
):
    """
    Endpoint for Web GUI to display the analysis dashboard,
    supporting filtering, search, and trace inspection.
    """
    results = list(_analysis_store.values())

    if device_id:
        results = [r for r in results if r.device_id.lower() == device_id.lower()]
    if result_status:
        results = [r for r in results if r.result_status.lower() == result_status.lower()]
    if protocol:
        results = [
            r for r in results if any(m.protocol.lower() == protocol.lower() for m in r.trace_messages)
        ]
    if search:
        search_lower = search.lower()
        results = [
            r for r in results
            if search_lower in r.summary.lower()
            or search_lower in r.analysis_id.lower()
            or any(m.error_reason and search_lower in m.error_reason.lower() for m in r.trace_messages)
        ]

    results = results[:limit]

    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        xml_list = [r.model_dump(mode="json") for r in results]
        xml_output = dict_to_xml_str("TraceAnalysisList", {"analyses": xml_list})
        return Response(content=xml_output, media_type="application/xml")

    return results


@router.get("/analysis/{analysis_id}", summary="Get detailed trace analysis for Web GUI Detailed View")
async def get_analysis_detail(analysis_id: str, request: Request):
    """
    Endpoint for Web GUI to inspect failure findings,
    trace data visualization, and field comparisons for a specific analysis run.
    """
    if analysis_id not in _analysis_store:
        raise HTTPException(
            status_code=404,
            detail=f"Analysis run '{analysis_id}' not found.",
        )

    analysis_item = _analysis_store[analysis_id]
    accept_header = request.headers.get("accept", "").lower()
    if "application/xml" in accept_header or "text/xml" in accept_header:
        xml_output = dict_to_xml_str("AnalysisDetail", analysis_item.model_dump(mode="json"))
        return Response(content=xml_output, media_type="application/xml")

    return analysis_item


@router.post("/analysis/reset", summary="Reset trace analysis records back to initial demo state")
async def reset_analysis_store():
    """Wipes generated trace history and resets back to the initial demo run."""
    _analysis_store.clear()
    _seed_initial_trace_data()
    logger.info("Trace analysis store reset back to initial demo state.")
    return {
        "status": "SUCCESS",
        "message": "Trace analysis history reset to initial demo state.",
        "total_runs": len(_analysis_store),
    }


@router.post("/analysis", summary="Send post-analysis results to DBLTAS")
async def post_analysis(
    request: Request,
    client: TecWatchClient = Depends(get_client),
):
    """
    Accepts post-analysis results in JSON or XML format.
    Validates message length, mandatory fields, data types, and rejects unexpected content.
    Forwards validated data to the configured target server and stores it for GUI querying.
    """
    content_type = request.headers.get("content-type", "").lower()
    raw_body = await request.body()

    if not raw_body:
        raise HTTPException(
            status_code=400,
            detail="Request body cannot be empty. Mandatory analysis fields required.",
        )

    data_to_validate = None

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

    else:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported Content-Type '{content_type}'. Must be 'application/json' or 'application/xml'.",
        )

    # Validate against strict Pydantic model (rejects missing fields, invalid types, extra fields)
    try:
        validated_request = AnalysisResultRequest.model_validate(data_to_validate)
    except ValidationError as val_err:
        from fastapi.exceptions import RequestValidationError
        raise RequestValidationError(val_err.errors())

    # Forward to configured target server
    upstream_payload = validated_request.model_dump(mode="json")
    await client.send_analysis_result(upstream_payload)

    # Store for GUI dashboard access
    _analysis_store[validated_request.analysis_id] = validated_request

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
