from typing import Any, Dict, Optional
import httpx
from config.settings import ConfigManager
from src.utils.logger import logger


class UpstreamError(Exception):
    """Base exception for upstream communication failures."""
    pass


class UpstreamConnectionError(UpstreamError):
    """Raised when unable to connect to the target server."""
    pass


class UpstreamTimeoutError(UpstreamError):
    """Raised when the target server times out."""
    pass


class UpstreamResponseError(UpstreamError):
    """Raised when upstream server returns an error code."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Upstream returned HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class TecWatchClient:
    """
    Client for communicating with the target tecWatch / DBLTAS backend.
    Reads server configuration dynamically on each request to support
    server switching without code changes or restarts.
    """

    def __init__(self, timeout: Optional[float] = None):
        self._timeout = timeout

    @property
    def config(self):
        return ConfigManager.get_instance().config

    @property
    def base_url(self) -> str:
        server = self.config.server
        return f"http://{server.host}:{server.port}"

    @property
    def timeout(self) -> float:
        return self._timeout or self.config.server.timeout_seconds

    async def fetch_status(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch status information from the configured tecWatch server."""
        endpoint = self.config.api.status_endpoint
        url = f"{self.base_url}{endpoint}"
        params = {"device_id": device_id} if device_id else {}

        logger.info(f"Connecting to upstream tecWatch server at: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                if response.status_code >= 400:
                    raise UpstreamResponseError(response.status_code, response.text)
                return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to tecWatch server at {url}: {e}")
            raise UpstreamConnectionError(
                f"Cannot connect to target server at {self.base_url}. Verify server is running and accessible."
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout while waiting for tecWatch server at {url}: {e}")
            raise UpstreamTimeoutError(
                f"Connection to target server at {self.base_url} timed out after {self.timeout}s."
            ) from e

    async def send_analysis_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send post-analysis results to the configured target server."""
        endpoint = self.config.api.result_endpoint
        url = f"{self.base_url}{endpoint}"

        logger.info(f"Forwarding post-analysis result to upstream server at: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                if response.status_code >= 400:
                    raise UpstreamResponseError(response.status_code, response.text)
                return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to target server at {url}: {e}")
            raise UpstreamConnectionError(
                f"Cannot connect to target server at {self.base_url}. Verify server is running and accessible."
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout while posting to target server at {url}: {e}")
            raise UpstreamTimeoutError(
                f"Connection to target server at {self.base_url} timed out after {self.timeout}s."
            ) from e
