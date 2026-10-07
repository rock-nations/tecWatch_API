from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


def create_mock_tecwatch_server() -> FastAPI:
    """
    Creates an ASGI FastAPI app that simulates a real tecWatch hardware server
    and DBLTAS result ingestion backend for testing and development.

    The simulated tecWatch monitors the SCI-TDS interface of the test bench. Its status reflects
    the end state of the Real-OC test run of 2026-10-02 (GFM-A 34W1 disturbed, test unit stopped).
    """
    mock_app = FastAPI(title="tecWatch Target Server Simulator")

    @mock_app.get("/api/status")
    async def get_mock_status(device_id: str = "DETHMM AZA34##0001") -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "device_id": device_id,
            "status": "DEGRADED",
            "timestamp": now.isoformat(),
            "link": {
                "state": "CONNECTED",
                "protocol": "SCI-TDS Baseline 5 over RaSTA",
                "btp_version": "01",
                "version_check": "BTP-Versionswerte gleich",
                "local_endpoint": "DETHMM ZE 35##0001 (1.208.188.16:24001)",
                "remote_endpoint": f"{device_id} (10.129.15.2:24001)",
                "heartbeat_interval_ms": 300,
                "last_message_at": (now - timedelta(milliseconds=120)).isoformat(),
            },
            "track_sections": [
                {
                    "section": "34W1",
                    "section_type": "GFM-A",
                    "occupancy": "DISTURBED",
                    "resettable": False,
                    "axle_count": 0,
                    "since": "2026-10-02T10:27:06.906Z",
                }
            ],
            "test_execution": {
                "state": "STOPPED",
                "test_unit": "TDS-Test",
                "configuration": "ZE_RealOC_Stimulation.cfg",
                "current_test_case": "TC_NPRO.295.00522.01",
                "passed": 2,
                "failed": 2,
                "inconclusive": 1,
            },
            "active_alerts": [
                "GFM-A 34W1 gestört (disturbed) and nicht grundstellbar: AZG/AZGH will be discarded",
                "Test unit stopped manually: TC_NPRO.295.00522.01 inconclusive",
            ],
        }

    @mock_app.post("/api/analysis")
    async def post_mock_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not payload.get("analysis_id"):
            raise HTTPException(status_code=400, detail="Missing analysis_id")
        return {
            "status": "SUCCESS",
            "message": "Analysis result accepted by target server",
            "analysis_id": payload["analysis_id"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    return mock_app


mock_app = create_mock_tecwatch_server()

if __name__ == "__main__":
    import uvicorn
    print("Starting mock tecWatch / DBLTAS backend on port 8080...")
    uvicorn.run(mock_app, host="127.0.0.1", port=8080)
