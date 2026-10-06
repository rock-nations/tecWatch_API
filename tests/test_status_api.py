import pytest
import defusedxml.ElementTree as DefusedET
from src.services.client import UpstreamConnectionError


@pytest.mark.asyncio
async def test_get_status_json_success(client):
    response = await client.get("/api/status?device_id=TW-101", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data["device_id"] == "TW-101"
    assert data["status"] == "OPERATIONAL"
    assert isinstance(data["battery_level"], (int, float))
    assert isinstance(data["uptime_seconds"], int)
    assert isinstance(data["temperature"], (int, float))
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_get_status_xml_success(client):
    response = await client.get("/api/status?device_id=TW-101", headers={"Accept": "application/xml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    # Verify XML content is parseable and contains required tags
    root = DefusedET.fromstring(response.content)
    assert root.tag == "tecWatchStatus"
    assert root.find("device_id").text == "TW-101"
    assert root.find("status").text == "OPERATIONAL"


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
