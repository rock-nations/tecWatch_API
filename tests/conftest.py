import json
import os
import pytest
from httpx import ASGITransport, AsyncClient
from config.settings import ConfigManager
from src.main import create_app
from src.services.mock_server import create_mock_tecwatch_server


@pytest.fixture(autouse=True)
def clean_config():
    """Ensure each test runs with a pristine config state."""
    # Reset any test env vars
    for key in [
        "TECWATCH_SERVER_HOST",
        "TECWATCH_SERVER_PORT",
        "TECWATCH_STATUS_ENDPOINT",
        "TECWATCH_RESULT_ENDPOINT",
        "TECWATCH_ANALYSIS_REPORT_PATH",
    ]:
        os.environ.pop(key, None)
    ConfigManager.reset_instance()
    yield
    ConfigManager.reset_instance()


@pytest.fixture
def valid_report():
    """A small analysis report in the data-analysis-report.json format."""
    return {
        "analysis_id": "TRACE-RUN-TEST-0001",
        "device_id": "DETHMM AZA34##0001",
        "timestamp": "2026-10-02T10:23:59.953Z",
        "analysis_type": "TRACE_COMMUNICATION",
        "result_status": "FAILED",
        "summary": "1 of 1 test cases failed: MELDUNG_GFMA_BELEGUNGSZUSTAND is one byte short.",
        "trace_messages": [
            {
                "message_id": "frame-11-1",
                "timestamp": "2026-10-02T10:24:03.601Z",
                "time_s": 3.648055,
                "sender": "DETHMM ZE 35##0001",
                "receiver": "DETHMM AZA34##0001",
                "protocol": "SCI-TDS BL5 over RaSTA",
                "message_type": "KOMMANDO_BTP_VERSIONSABGLEICH",
                "message_code": "0x0024",
                "direction": "ZE→AZ",
                "length": 44,
                "fields": {"btp_version": 1},
                "test_case": None,
                "status": "OK",
                "error_reason": None,
            },
            {
                "message_id": "frame-380-2",
                "timestamp": "2026-10-02T10:27:00.241Z",
                "time_s": 180.287372,
                "sender": "34W1",
                "receiver": "DETHMM ZE 35##0001",
                "protocol": "SCI-TDS BL5 over RaSTA",
                "message_type": "MELDUNG_GFMA_BELEGUNGSZUSTAND",
                "message_code": "0x0007",
                "direction": "AZ→ZE",
                "length": 47,
                "fields": {"belegung": 1, "grundstellbar": 0, "achszaehlfuellstand": 0},
                "test_case": "TC_NPRO.295.02288.01",
                "status": "FAILED",
                "error_reason": "Message Length Error",
            },
        ],
        "failure_findings": [
            {
                "message_id": "frame-380-2",
                "expected_length": 48,
                "actual_length": 47,
                "result": "Message Length Error",
                "test_case": "TC_NPRO.295.02288.01",
                "timestamp": "2026-10-02T10:27:00.241Z",
                "time_s": 180.287372,
                "category": "incorrect_length",
                "description": "Test_Description step 2 expects a 48-byte telegram, the device sends 47 bytes",
                "confidence": 0.9,
                "evidence": ["RealOCWorking_TDS_21026.pcapng frame 380 telegram 2"],
            },
            {
                "message_id": None,
                "expected_length": None,
                "actual_length": None,
                "result": "Test Aborted",
                "test_case": "TC_NPRO.295.00522.01",
                "timestamp": "2026-10-02T10:32:08.274Z",
                "time_s": 488.321,
                "category": "test_aborted",
                "description": "Test execution stopped: test unit stopped by the user",
                "confidence": 1.0,
                "evidence": [],
            },
        ],
        "data_comparisons": [
            {
                "field": "Length MELDUNG_GFMA_BELEGUNGSZUSTAND (Test_Description step 2)",
                "expected": "48",
                "actual": "47",
                "result": "Error",
                "test_case": "TC_NPRO.295.02288.01",
            },
            {
                "field": "RaSTA message gap",
                "expected": "<= 750 ms",
                "actual": "max 306 ms",
                "result": "OK",
                "test_case": None,
            },
        ],
    }


@pytest.fixture
def use_report(tmp_path):
    """Writes a report file (dict as JSON, or raw str/bytes) and points the active config at it."""
    def _use_report(content):
        report_file = tmp_path / "analysis-report.json"
        if isinstance(content, dict):
            report_file.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        elif isinstance(content, bytes):
            report_file.write_bytes(content)
        else:
            report_file.write_text(content, encoding="utf-8")
        ConfigManager.get_instance().config.analysis.report_path = str(report_file)
        return report_file

    return _use_report


@pytest.fixture
def mock_upstream_app():
    return create_mock_tecwatch_server()


@pytest.fixture
def api_app():
    return create_app()


import pytest_asyncio


@pytest_asyncio.fixture
async def client(api_app, mock_upstream_app):
    """
    Creates an async test client where upstream requests to http://127.0.0.1:8080 or http://192.168.1.10:8080
    are routed to the mock_upstream_app.
    """
    mock_transport = ASGITransport(app=mock_upstream_app)
    app_transport = ASGITransport(app=api_app)

    # Configure ConfigManager to point to mock upstream
    cfg = ConfigManager.get_instance().config
    cfg.server.host = "testserver"
    cfg.server.port = 8080

    async with AsyncClient(
        transport=mock_transport,
        base_url="http://testserver:8080"
    ) as upstream_client:
        # Patch the TecWatchClient to use mock_transport for upstream
        from src.services.client import TecWatchClient
        original_fetch = TecWatchClient.fetch_status
        original_send = TecWatchClient.send_analysis_result

        async def patched_fetch(self, device_id=None):
            endpoint = self.config.api.status_endpoint
            params = {"device_id": device_id} if device_id else {}
            res = await upstream_client.get(endpoint, params=params)
            return res.json()

        async def patched_send(self, payload):
            endpoint = self.config.api.result_endpoint
            res = await upstream_client.post(endpoint, json=payload)
            return res.json()

        TecWatchClient.fetch_status = patched_fetch
        TecWatchClient.send_analysis_result = patched_send

        async with AsyncClient(transport=app_transport, base_url="http://gateway:8000") as test_client:
            yield test_client

        TecWatchClient.fetch_status = original_fetch
        TecWatchClient.send_analysis_result = original_send
