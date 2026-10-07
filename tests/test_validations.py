import json
import pytest
from config.settings import ConfigManager


@pytest.mark.asyncio
async def test_message_length_too_large(client):
    # Temporarily set max payload to 1024 bytes
    ConfigManager.get_instance().config.api.max_payload_bytes = 1024
    huge_summary = "X" * 2000

    payload = {
        "analysis_id": "AN-100",
        "device_id": "TW-01",
        "timestamp": "2026-10-03T12:00:00Z",
        "analysis_type": "TRACE_COMMUNICATION",
        "result_status": "PASSED",
        "summary": huge_summary,
    }

    body = json.dumps(payload).encode("utf-8")
    response = await client.post(
        "/api/analysis",
        content=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    assert response.status_code == 413
    data = response.json()
    assert data["error"] == "Payload Too Large"
    assert "exceeds configured limit" in data["detail"]


@pytest.mark.asyncio
async def test_mandatory_fields_missing(client):
    # Missing 'summary' and 'analysis_type'
    incomplete_payload = {
        "analysis_id": "AN-100",
        "device_id": "TW-01",
        "timestamp": "2026-10-03T12:00:00Z",
        "result_status": "PASSED",
    }

    response = await client.post(
        "/api/analysis",
        json=incomplete_payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "Validation Error"
    errors = [e["field"] for e in data["validation_errors"]]
    assert any("analysis_type" in f for f in errors)
    assert any("summary" in f for f in errors)


@pytest.mark.asyncio
async def test_data_types_invalid(client, valid_report):
    # analysis_id should be string, passing a list
    # expected_length in failure_findings should be an int, passing string "sixty"
    # length in trace_messages should be an int, passing the numeric string "47"
    invalid_type_payload = valid_report
    invalid_type_payload["analysis_id"] = ["not", "a", "string"]
    invalid_type_payload["failure_findings"][0]["expected_length"] = "sixty"
    invalid_type_payload["trace_messages"][1]["length"] = "47"

    response = await client.post(
        "/api/analysis",
        json=invalid_type_payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "Validation Error"
    errors = {e["field"]: e["message"] for e in data["validation_errors"]}
    assert errors["analysis_id"].startswith("Invalid data type")
    assert errors["failure_findings -> 0 -> expected_length"].startswith("Invalid data type")
    assert errors["trace_messages -> 1 -> length"].startswith("Invalid data type")


@pytest.mark.asyncio
async def test_unexpected_content_forbidden(client):
    # Including undeclared field 'unauthorized_field'
    extra_field_payload = {
        "analysis_id": "AN-100",
        "device_id": "TW-01",
        "timestamp": "2026-10-03T12:00:00Z",
        "analysis_type": "TRACE_COMMUNICATION",
        "result_status": "PASSED",
        "summary": "Sample summary",
        "unauthorized_field": "HACKER_PAYLOAD",  # Unexpected extra content!
    }

    response = await client.post(
        "/api/analysis",
        json=extra_field_payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "Validation Error"
    error_messages = [e["message"] for e in data["validation_errors"]]
    assert any("Unexpected field" in m or "Extra inputs are not permitted" in m for m in error_messages)


@pytest.mark.asyncio
async def test_invalid_json_syntax(client):
    # Malformed JSON (trailing comma without value / missing braces)
    malformed_json = b'{"analysis_id": "AN-100", "device_id": '

    response = await client.post(
        "/api/analysis",
        content=malformed_json,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "Invalid JSON"
    assert "Malformed JSON syntax" in data["detail"]


@pytest.mark.asyncio
async def test_invalid_xml_syntax(client):
    # Malformed XML (unclosed tag)
    malformed_xml = b"<AnalysisResult><analysis_id>AN-100</analysis_id><device_id>TW-1"

    response = await client.post(
        "/api/analysis",
        content=malformed_xml,
        headers={"Content-Type": "application/xml"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "Invalid XML"
    assert "Invalid XML syntax" in data["detail"]


@pytest.mark.asyncio
async def test_unsupported_media_type(client):
    response = await client.post(
        "/api/analysis",
        content=b"plain text payload",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    data = response.json()
    assert "Unsupported Content-Type" in data["detail"]


@pytest.mark.asyncio
async def test_field_length_bounds(client):
    # analysis_id too short (min length is 3)
    too_short_payload = {
        "analysis_id": "A",
        "device_id": "TW-01",
        "timestamp": "2026-10-03T12:00:00Z",
        "analysis_type": "TRACE_COMMUNICATION",
        "result_status": "PASSED",
        "summary": "Valid summary",
    }
    response = await client.post("/api/analysis", json=too_short_payload)
    assert response.status_code == 422
