import json
from pathlib import Path
import pytest
import defusedxml.ElementTree as DefusedET
from src.models.status import StatusResponse
from src.services.client import UpstreamConnectionError

DEVICE_ID = "DETHMM AZA34##0001"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "docs" / "examples"


def test_documented_status_example_is_valid():
    StatusResponse.model_validate(json.loads((EXAMPLES_DIR / "status_response.json").read_text(encoding="utf-8")))


@pytest.mark.asyncio
async def test_get_status_json_success(client):
    response = await client.get("/api/status", params={"device_id": DEVICE_ID}, headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data["device_id"] == DEVICE_ID
    assert data["status"] in {"OPERATIONAL", "DEGRADED", "DISCONNECTED", "FAULT"}
    assert "timestamp" in data

    link = data["link"]
    assert link["state"] == "CONNECTED"
    assert link["protocol"] == "SCI-TDS Baseline 5 over RaSTA"
    assert isinstance(link["heartbeat_interval_ms"], int)
    assert DEVICE_ID in link["remote_endpoint"]

    section = data["track_sections"][0]
    assert section["section"] == "34W1"
    assert section["occupancy"] in {"FREE", "OCCUPIED", "DISTURBED"}
    assert isinstance(section["resettable"], bool)

    execution = data["test_execution"]
    assert execution["state"] in {"IDLE", "RUNNING", "STOPPED", "COMPLETED"}
    assert execution["passed"] + execution["failed"] + execution["inconclusive"] >= 0
    assert isinstance(data["active_alerts"], list)


@pytest.mark.asyncio
async def test_get_status_xml_success(client):
    response = await client.get("/api/status", params={"device_id": DEVICE_ID}, headers={"Accept": "application/xml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    # Verify XML content is parseable and contains required tags
    root = DefusedET.fromstring(response.content)
    assert root.tag == "tecWatchStatus"
    assert root.find("device_id").text == DEVICE_ID
    assert root.find("link/state").text == "CONNECTED"
    assert root.find("track_sections/section").text == "34W1"
    assert root.find("test_execution/state").text is not None


@pytest.mark.asyncio
async def test_get_status_upstream_failure(client, monkeypatch):
    from src.services.client import TecWatchClient

    async def mock_fail_fetch(self, device_id=None):
        raise UpstreamConnectionError("Target server unreachable")

    monkeypatch.setattr(TecWatchClient, "fetch_status", mock_fail_fetch)

    response = await client.get("/api/status")
    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "Bad Gateway"
    assert "Target server unreachable" in data["detail"]


@pytest.mark.asyncio
async def test_get_status_upstream_data_invalid(client, monkeypatch):
    from src.services.client import TecWatchClient

    async def mock_old_format_fetch(self, device_id=None):
        # Old wearable-style status: unknown status value, missing link/test execution, unexpected fields
        return {
            "device_id": "TW-DEFAULT",
            "status": "STANDBY",
            "battery_level": 92.5,
            "timestamp": "2026-10-02T12:00:00Z",
        }

    monkeypatch.setattr(TecWatchClient, "fetch_status", mock_old_format_fetch)

    response = await client.get("/api/status")
    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "Bad Gateway"
    assert "failed validation" in data["detail"]
    errors = {e["field"]: e["type"] for e in data["validation_errors"]}
    assert errors["status"] == "literal_error"
    assert errors["link"] == "missing"
    assert errors["test_execution"] == "missing"
    assert errors["battery_level"] == "extra_forbidden"
