from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from src.services.simulated_status import DEFAULT_DEVICE_ID, simulated_status


def create_mock_tecwatch_server() -> FastAPI:
    """
    Creates an ASGI FastAPI app that simulates a real tecWatch hardware server
    and DBLTAS result ingestion backend for testing and development.

    The simulated tecWatch monitors the SCI-TDS interface of the test bench. Its status reflects
    the end state of the Real-OC test run of 2026-10-02 (GFM-A 34W1 disturbed, test unit stopped).
    """
    mock_app = FastAPI(title="tecWatch Target Server Simulator")

    @mock_app.get("/api/status")
    async def get_mock_status(device_id: str = DEFAULT_DEVICE_ID) -> Dict[str, Any]:
        return simulated_status(device_id)

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
