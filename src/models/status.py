from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class StatusQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: Optional[StrictStr] = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Optional device ID filter",
    )


class LinkStatus(BaseModel):
    """SCI-TDS interface between ESTW-ZE and the object controller, observed by tecWatch."""
    model_config = ConfigDict(extra="forbid")

    state: Literal["CONNECTED", "CONNECTING", "DISCONNECTED"] = Field(
        ...,
        description="Mandatory RaSTA session state",
    )
    protocol: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Mandatory protocol and baseline (e.g. SCI-TDS Baseline 5 over RaSTA)",
    )
    btp_version: StrictStr = Field(
        ...,
        min_length=1,
        max_length=8,
        description="Mandatory negotiated BTP version",
    )
    version_check: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Mandatory result of the BTP version check",
    )
    local_endpoint: StrictStr = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Mandatory ESTW-ZE endpoint (technical ID and address)",
    )
    remote_endpoint: StrictStr = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Mandatory object controller endpoint (technical ID and address)",
    )
    heartbeat_interval_ms: StrictInt = Field(
        ...,
        ge=0,
        le=60000,
        description="Mandatory RaSTA heartbeat interval in milliseconds",
    )
    last_message_at: datetime = Field(
        ...,
        description="Mandatory ISO 8601 timestamp of the last received RaSTA message",
    )


class TrackSectionStatus(BaseModel):
    """Track vacancy detection section (GFM-A) reported via telegram 3.4.11."""
    model_config = ConfigDict(extra="forbid")

    section: StrictStr = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Mandatory section name (e.g. 34W1)",
    )
    section_type: StrictStr = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Mandatory section type (e.g. GFM-A)",
    )
    occupancy: Literal["FREE", "OCCUPIED", "DISTURBED"] = Field(
        ...,
        description="Mandatory Belegungszustand (frei, belegt, gestört)",
    )
    resettable: StrictBool = Field(
        ...,
        description="Mandatory Grundstellbarkeit: true if AZG/AZGH would be accepted",
    )
    axle_count: StrictInt = Field(
        ...,
        ge=0,
        le=65535,
        description="Mandatory axle count fill level",
    )
    since: datetime = Field(
        ...,
        description="Mandatory ISO 8601 timestamp since when the state is reported",
    )


class TestExecutionStatus(BaseModel):
    """Test unit running on the test system (CANoe)."""
    model_config = ConfigDict(extra="forbid")

    state: Literal["IDLE", "RUNNING", "STOPPED", "COMPLETED"] = Field(
        ...,
        description="Mandatory test unit state",
    )
    test_unit: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Mandatory test unit / test configuration name",
    )
    configuration: StrictStr = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Mandatory CANoe configuration",
    )
    current_test_case: Optional[StrictStr] = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Test case currently or last executed",
    )
    passed: StrictInt = Field(..., ge=0, description="Mandatory number of passed test cases")
    failed: StrictInt = Field(..., ge=0, description="Mandatory number of failed test cases")
    inconclusive: StrictInt = Field(..., ge=0, description="Mandatory number of inconclusive test cases")


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Mandatory technical ID of the monitored object controller",
    )
    status: Literal["OPERATIONAL", "DEGRADED", "DISCONNECTED", "FAULT"] = Field(
        ...,
        description="Mandatory overall status for the trial operator",
    )
    timestamp: datetime = Field(
        ...,
        description="Mandatory ISO 8601 timestamp",
    )
    link: LinkStatus = Field(
        ...,
        description="Mandatory SCI-TDS link status",
    )
    track_sections: List[TrackSectionStatus] = Field(
        default_factory=list,
        max_length=50,
        description="Monitored track sections",
    )
    test_execution: TestExecutionStatus = Field(
        ...,
        description="Mandatory test execution status",
    )
    active_alerts: List[StrictStr] = Field(
        default_factory=list,
        max_length=50,
        description="List of active alerts for the trial operator",
    )
    source: Literal["tecwatch", "simulated"] = Field(
        default="tecwatch",
        description="Set by the API: 'tecwatch' for the server's status, 'simulated' for the built-in status "
                    "returned while the tecWatch server cannot be reached",
    )
