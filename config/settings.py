import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, field_validator

# Backend project folder; relative file paths in the configuration are resolved against it
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ServerConfig(BaseModel):
    host: str = Field(default="127.0.0.1", description="Target server IP or hostname")
    port: int = Field(default=8080, ge=1, le=65535, description="Target server port")
    timeout_seconds: float = Field(default=5.0, gt=0, description="HTTP request timeout in seconds")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class ApiConfig(BaseModel):
    status_endpoint: str = Field(default="/api/status", description="Status endpoint path")
    result_endpoint: str = Field(default="/api/analysis", description="Post-analysis endpoint path")
    max_payload_bytes: int = Field(default=1048576, ge=1024, description="Max allowed payload size in bytes")
    status_fallback: bool = Field(
        default=True,
        description="GET /api/status returns the built-in simulated status when the tecWatch server cannot be reached",
    )

    @field_validator("status_endpoint", "result_endpoint")
    @classmethod
    def ensure_leading_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            return f"/{v}"
        return v


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


class AnalysisConfig(BaseModel):
    report_path: str = Field(
        default="data/data-analysis-report.json",
        description="Analysis report JSON file served by GET /api/analysis",
    )
    scenarios_path: str = Field(
        default="data/analysis-scenarios.json",
        description="Analysis scenarios (findings) JSON file served by GET /api/analysis/scenarios",
    )
    max_report_bytes: int = Field(default=1048576, ge=1024, description="Max allowed size of each analysis file in bytes")
    max_upload_bytes: int = Field(
        default=52428800, ge=1024, description="Max size of each file uploaded to POST /api/analysis/upload in bytes"
    )

    @property
    def max_upload_request_bytes(self) -> int:
        """Request size limit of the upload endpoint: two files plus the multipart framing."""
        return 2 * self.max_upload_bytes + 65536

    @property
    def resolved_report_path(self) -> Path:
        return _resolve_path(self.report_path)

    @property
    def resolved_scenarios_path(self) -> Path:
        return _resolve_path(self.scenarios_path)


class GatewayConfig(BaseModel):
    listen_host: str = Field(default="0.0.0.0", description="Gateway host to bind to")
    listen_port: int = Field(default=8000, ge=1, le=65535, description="Gateway port to bind to")
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="logs/tecwatch_api.log", description="Path to log file")


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _config: AppConfig

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(
            config_path
            or os.environ.get("TECWATCH_CONFIG_PATH")
            or Path(__file__).resolve().parent / "config.yaml"
        )
        self._config = self.load()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = cls(config_path)
        elif config_path is not None and Path(config_path) != cls._instance.config_path:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def load(self) -> AppConfig:
        raw_data = {}
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, dict):
                    raw_data = content

        # Apply environment variable overrides if provided
        if "TECWATCH_SERVER_HOST" in os.environ:
            raw_data.setdefault("server", {})["host"] = os.environ["TECWATCH_SERVER_HOST"]
        if "TECWATCH_SERVER_PORT" in os.environ:
            raw_data.setdefault("server", {})["port"] = int(os.environ["TECWATCH_SERVER_PORT"])
        if "TECWATCH_STATUS_ENDPOINT" in os.environ:
            raw_data.setdefault("api", {})["status_endpoint"] = os.environ["TECWATCH_STATUS_ENDPOINT"]
        if "TECWATCH_RESULT_ENDPOINT" in os.environ:
            raw_data.setdefault("api", {})["result_endpoint"] = os.environ["TECWATCH_RESULT_ENDPOINT"]
        if "TECWATCH_STATUS_FALLBACK" in os.environ:
            raw_data.setdefault("api", {})["status_fallback"] = os.environ["TECWATCH_STATUS_FALLBACK"]
        if "TECWATCH_ANALYSIS_REPORT_PATH" in os.environ:
            raw_data.setdefault("analysis", {})["report_path"] = os.environ["TECWATCH_ANALYSIS_REPORT_PATH"]
        if "TECWATCH_ANALYSIS_SCENARIOS_PATH" in os.environ:
            raw_data.setdefault("analysis", {})["scenarios_path"] = os.environ["TECWATCH_ANALYSIS_SCENARIOS_PATH"]

        self._config = AppConfig(**raw_data)
        return self._config

    def reload(self) -> AppConfig:
        return self.load()

    @property
    def config(self) -> AppConfig:
        return self._config


def get_config() -> AppConfig:
    return ConfigManager.get_instance().config
