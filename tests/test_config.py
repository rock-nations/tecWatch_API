import os
from pathlib import Path
import pytest
import yaml
from config.settings import ConfigManager


def test_default_config_loading():
    mgr = ConfigManager()
    cfg = mgr.config
    assert cfg.server.port == 8080
    assert cfg.api.status_endpoint == "/api/status"
    assert cfg.api.result_endpoint == "/api/analysis"
    assert cfg.api.max_payload_bytes == 1048576
    assert cfg.api.status_fallback is True
    assert cfg.analysis.report_path == "data/data-analysis-report.json"
    assert cfg.analysis.scenarios_path == "data/analysis-scenarios.json"
    assert cfg.analysis.max_report_bytes == 1048576
    assert cfg.analysis.resolved_report_path.is_file()
    assert cfg.analysis.resolved_scenarios_path.is_file()


def test_environment_variable_override(monkeypatch, tmp_path):
    report_file = tmp_path / "report.json"
    scenarios_file = tmp_path / "scenarios.json"
    monkeypatch.setenv("TECWATCH_SERVER_HOST", "10.0.0.99")
    monkeypatch.setenv("TECWATCH_SERVER_PORT", "9999")
    monkeypatch.setenv("TECWATCH_STATUS_ENDPOINT", "/custom/status")
    monkeypatch.setenv("TECWATCH_RESULT_ENDPOINT", "/custom/analysis")
    monkeypatch.setenv("TECWATCH_ANALYSIS_REPORT_PATH", str(report_file))
    monkeypatch.setenv("TECWATCH_ANALYSIS_SCENARIOS_PATH", str(scenarios_file))
    monkeypatch.setenv("TECWATCH_STATUS_FALLBACK", "false")

    mgr = ConfigManager()
    cfg = mgr.load()

    assert cfg.server.host == "10.0.0.99"
    assert cfg.server.port == 9999
    assert cfg.server.base_url == "http://10.0.0.99:9999"
    assert cfg.api.status_endpoint == "/custom/status"
    assert cfg.api.result_endpoint == "/custom/analysis"
    assert cfg.analysis.resolved_report_path == report_file
    assert cfg.analysis.resolved_scenarios_path == scenarios_file
    assert cfg.api.status_fallback is False


def test_relative_report_path_resolves_against_backend_folder(tmp_path):
    test_yaml = tmp_path / "config.yaml"
    test_yaml.write_text(yaml.dump({"analysis": {"report_path": "../shared/report.json"}}), encoding="utf-8")

    cfg = ConfigManager(config_path=str(test_yaml)).config
    backend_folder = Path(__file__).resolve().parent.parent
    assert cfg.analysis.resolved_report_path == backend_folder / "../shared/report.json"


def test_dynamic_server_switching_without_code_change(tmp_path):
    # Create temporary config pointing to Server A
    test_yaml = tmp_path / "config.yaml"
    initial_data = {
        "server": {"host": "192.168.1.10", "port": 8080},
        "api": {"status_endpoint": "/api/status", "result_endpoint": "/api/analysis"},
    }
    test_yaml.write_text(yaml.dump(initial_data), encoding="utf-8")

    mgr = ConfigManager(config_path=str(test_yaml))
    assert mgr.config.server.base_url == "http://192.168.1.10:8080"

    # Now simulate switching to Server B by simply modifying configuration
    updated_data = {
        "server": {"host": "10.200.50.2", "port": 9090},
        "api": {"status_endpoint": "/api/v2/status", "result_endpoint": "/api/v2/analysis"},
    }
    test_yaml.write_text(yaml.dump(updated_data), encoding="utf-8")

    # Reload without code change
    reloaded_cfg = mgr.reload()
    assert reloaded_cfg.server.host == "10.200.50.2"
    assert reloaded_cfg.server.port == 9090
    assert reloaded_cfg.server.base_url == "http://10.200.50.2:9090"
    assert reloaded_cfg.api.status_endpoint == "/api/v2/status"


@pytest.mark.asyncio
async def test_api_config_endpoints(client):
    # Test GET /api/config
    get_res = await client.get("/api/config")
    assert get_res.status_code == 200
    cfg_data = get_res.json()
    assert "server" in cfg_data
    assert "api" in cfg_data
    assert "analysis" in cfg_data
    assert "gateway" in cfg_data

    # Test POST /api/config/reload
    reload_res = await client.post("/api/config/reload")
    assert reload_res.status_code == 200
    reload_data = reload_res.json()
    assert reload_data["status"] == "SUCCESS"
    assert "new_target" in reload_data

