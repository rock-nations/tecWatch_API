import pytest
import defusedxml.ElementTree as DefusedET
from src.services.client import UpstreamConnectionError


@pytest.mark.asyncio
async def test_get_analysis_list_and_filter(client):
    # Test listing all analysis items
    response = await client.get("/api/analysis")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    first = data[0]
    assert "analysis_id" in first
    assert "trace_messages" in first
    assert "failure_findings" in first
    assert "data_comparisons" in first

    # Test filtering by result_status=FAILED
    failed_res = await client.get("/api/analysis?result_status=FAILED")
    assert failed_res.status_code == 200
    failed_data = failed_res.json()
    assert all(item["result_status"] == "FAILED" for item in failed_data)

    # Test search query
    search_res = await client.get("/api/analysis?search=CAN")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert len(search_data) >= 1


@pytest.mark.asyncio
async def test_get_analysis_detail_success_and_not_found(client):
    # Test valid item
    response = await client.get("/api/analysis/TRACE-RUN-1001")
    assert response.status_code == 200
    data = response.json()
    assert data["analysis_id"] == "TRACE-RUN-1001"
    assert len(data["failure_findings"]) >= 1
    assert data["failure_findings"][0]["message_id"] == "127"
    assert data["failure_findings"][0]["expected_length"] == 64
    assert data["failure_findings"][0]["actual_length"] == 60
    assert data["failure_findings"][0]["result"] == "Message Length Error"

    # Test 404 for unknown item
    not_found = await client.get("/api/analysis/NON-EXISTENT-ID")
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_post_analysis_json_success(client):
    payload = {
        "analysis_id": "TRACE-TEST-2002",
        "device_id": "TW-55",
        "timestamp": "2026-10-03T12:00:00Z",
        "analysis_type": "TRACE_COMMUNICATION",
        "result_status": "PASSED",
        "summary": "All communication packets matched expected schema.",
        "trace_messages": [
            {
                "timestamp": "2026-10-03T12:00:00Z",
                "sender": "NODE_A",
                "receiver": "NODE_B",
                "protocol": "TCP",
                "message_type": "HANDSHAKE",
                "status": "OK",
                "error_reason": None,
            }
        ],
        "failure_findings": [],
        "data_comparisons": [
            {"field": "Status", "expected": "READY", "actual": "READY", "result": "OK"}
        ],
    }

    response = await client.post(
        "/api/analysis",
        json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["analysis_id"] == "TRACE-TEST-2002"
    assert "processed_at" in data


@pytest.mark.asyncio
async def test_post_analysis_xml_success(client):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
<AnalysisResult>
  <analysis_id>TRACE-XML-3003</analysis_id>
  <device_id>TW-99</device_id>
  <timestamp>2026-10-03T12:10:00Z</timestamp>
  <analysis_type>TRACE_COMMUNICATION</analysis_type>
  <result_status>FAILED</result_status>
  <summary>Vibration frequencies steady under test load.</summary>
  <failure_findings>
    <message_id>127</message_id>
    <expected_length>64</expected_length>
    <actual_length>60</actual_length>
    <result>Message Length Error</result>
  </failure_findings>
  <data_comparisons>
    <field>Length</field>
    <expected>64</expected>
    <actual>60</actual>
    <result>Error</result>
  </data_comparisons>
</AnalysisResult>
"""

    response = await client.post(
        "/api/analysis",
        content=xml_payload.encode("utf-8"),
        headers={"Content-Type": "application/xml", "Accept": "application/xml"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    root = DefusedET.fromstring(response.content)
    assert root.tag == "AnalysisResultResponse"
    assert root.find("status").text == "SUCCESS"
    assert root.find("analysis_id").text == "TRACE-XML-3003"


@pytest.mark.asyncio
async def test_post_analysis_empty_body(client):
    response = await client.post(
        "/api/analysis",
        content=b"",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_post_analysis_upstream_failure(client, monkeypatch):
    from src.services.client import TecWatchClient

    async def mock_fail_send(self, payload):
        raise UpstreamConnectionError("DBLTAS server offline")

    monkeypatch.setattr(TecWatchClient, "send_analysis_result", mock_fail_send)

    payload = {
        "analysis_id": "TRACE-FAIL-9999",
        "device_id": "TW-55",
        "timestamp": "2026-10-03T12:00:00Z",
        "analysis_type": "TRACE",
        "result_status": "PASSED",
        "summary": "Check",
    }

    response = await client.post("/api/analysis", json=payload)
    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "Bad Gateway"
    assert "DBLTAS server offline" in data["detail"]


@pytest.mark.asyncio
async def test_post_analysis_reset(client):
    response = await client.post("/api/analysis/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["total_runs"] >= 1

