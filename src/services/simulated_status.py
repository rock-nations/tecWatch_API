"""
Built-in tecWatch status of the SCI-TDS test bench. The mock tecWatch server serves it, and
GET /api/status falls back to it when the configured tecWatch server cannot be reached
(api.status_fallback), so the Web GUI keeps working without a running tecWatch.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

DEFAULT_DEVICE_ID = "DETHMM AZA34##0001"


def simulated_status(device_id: str = DEFAULT_DEVICE_ID) -> Dict[str, Any]:
    """Status at the end of the Real-OC test run of 2026-10-02 (GFM-A 34W1 disturbed, test unit stopped)."""
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
