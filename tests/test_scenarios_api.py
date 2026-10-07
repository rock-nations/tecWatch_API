import json
import pytest
import defusedxml.ElementTree as DefusedET
from config.settings import ConfigManager


def _assert_invalid_scenarios(response, field, fragment):
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "Invalid Analysis Scenarios"
    assert any(
        e["field"].startswith(field) and fragment in (e["type"] + " " + e["message"])
        for e in data["validation_errors"]
    ), data["validation_errors"]


@pytest.mark.asyncio
async def test_get_scenarios_returns_shipped_file_unchanged(client, shipped_scenarios):
    response = await client.get("/api/analysis/scenarios")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data == shipped_scenarios
    assert data["source_file"].endswith(".xlsx")
    assert len(data["scenarios"]) >= 1


@pytest.mark.asyncio
async def test_get_scenarios_xml(client, shipped_scenarios):
    response = await client.get("/api/analysis/scenarios", headers={"Accept": "application/xml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    root = DefusedET.fromstring(response.content)
    assert root.tag == "AnalysisScenarios"
    assert len(root.findall("scenarios")) == len(shipped_scenarios["scenarios"])
    assert root.find("scenarios/id").text == shipped_scenarios["scenarios"][0]["id"]


@pytest.mark.asyncio
async def test_get_scenarios_rereads_file_on_every_request(client, use_scenarios, shipped_scenarios):
    scenarios_file = use_scenarios(shipped_scenarios)
    first = await client.get("/api/analysis/scenarios")
    assert first.json()["title"] == shipped_scenarios["title"]

    shipped_scenarios["title"] = "Re-run after OC parameter change"
    scenarios_file.write_text(json.dumps(shipped_scenarios), encoding="utf-8")

    second = await client.get("/api/analysis/scenarios")
    assert second.status_code == 200
    assert second.json()["title"] == "Re-run after OC parameter change"


@pytest.mark.asyncio
async def test_get_scenarios_file_missing(client, tmp_path):
    ConfigManager.get_instance().config.analysis.scenarios_path = str(tmp_path / "missing.json")

    response = await client.get("/api/analysis/scenarios")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "Analysis Scenarios Not Found"
    assert "missing.json" in data["detail"]


@pytest.mark.asyncio
async def test_get_scenarios_malformed_json(client, use_scenarios):
    use_scenarios('{"title": "SCI-TDS", ')

    response = await client.get("/api/analysis/scenarios")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "Invalid Analysis Scenarios"
    assert "Malformed JSON syntax" in data["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate, field, fragment",
    [
        pytest.param(lambda d: d["scenarios"][0].pop("recommendation"), "scenarios -> 0 -> recommendation", "missing", id="mandatory-field"),
        pytest.param(lambda d: d["scenarios"][0].update(severity="Critical"), "scenarios -> 0 -> severity", "literal_error", id="unknown-severity"),
        pytest.param(lambda d: d["scenarios"][0]["data_sources"][0].update(type="csv"), "scenarios -> 0 -> data_sources -> 0 -> type", "literal_error", id="unknown-source-type"),
        pytest.param(lambda d: d["scenarios"][0].update(owner="x"), "scenarios -> 0 -> owner", "extra_forbidden", id="unexpected-field"),
        pytest.param(lambda d: d["timeline"][0].update(pcap_frame="8"), "timeline -> 0 -> pcap_frame", "int_type", id="wrong-type"),
        pytest.param(lambda d: d["gfma_state_history"]["states"][0].update(axle_count="0"), "gfma_state_history -> states -> 0 -> axle_count", "string_pattern_mismatch", id="axle-count-format"),
        pytest.param(lambda d: d["gfma_state_history"]["states"][0].update(occupancy_code=6), "gfma_state_history -> states -> 0 -> occupancy_code", "less_than_equal", id="occupancy-code-range"),
        pytest.param(lambda d: d["scenarios"][1].update(id=d["scenarios"][0]["id"]), "", "scenario id must be unique", id="duplicate-scenario-id"),
        pytest.param(lambda d: d["timeline"][0].update(scenario_ids=["S99"]), "", "references unknown scenario 'S99'", id="unknown-scenario-reference"),
        pytest.param(lambda d: d["scenarios"][0].update(test_cases=["TC_NPRO.295.99999.01"]), "", "unknown test case 'TC_NPRO.295.99999.01'", id="unknown-test-case-reference"),
    ],
)
async def test_get_scenarios_invalid_document(client, use_scenarios, shipped_scenarios, mutate, field, fragment):
    mutate(shipped_scenarios)
    use_scenarios(shipped_scenarios)

    _assert_invalid_scenarios(await client.get("/api/analysis/scenarios"), field, fragment)
