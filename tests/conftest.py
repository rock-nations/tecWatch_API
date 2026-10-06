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
    for key in ["TECWATCH_SERVER_HOST", "TECWATCH_SERVER_PORT", "TECWATCH_STATUS_ENDPOINT", "TECWATCH_RESULT_ENDPOINT"]:
        os.environ.pop(key, None)
    ConfigManager.reset_instance()
    yield
    ConfigManager.reset_instance()


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
