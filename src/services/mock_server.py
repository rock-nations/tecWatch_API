from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


def create_mock_tecwatch_server() -> FastAPI:
    """
    Creates an ASGI FastAPI app that simulates a real tecWatch hardware server
    and DBLTAS result ingestion backend for testing and development.
    """
    mock_app = FastAPI(title="tecWatch Target Server Simulator")

    @mock_app.get("/api/status")
    async def get_mock_status(device_id: str = "TW-DEFAULT") -> Dict[str, Any]:
        return {
            "device_id": device_id,
            "status": "OPERATIONAL",
            "battery_level": 92.5,
            "uptime_seconds": 84200,
            "temperature": 27.8,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_alerts": [],
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
