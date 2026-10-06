from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


class StatusQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: Optional[StrictStr] = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Optional device ID filter",
    )


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Mandatory unique device identifier",
    )
    status: StrictStr = Field(
        ...,
        min_length=2,
        max_length=32,
        description="Mandatory device status (e.g. OPERATIONAL, STANDBY, ERROR)",
    )
    battery_level: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Mandatory battery level percentage (0.0 - 100.0)",
    )
    uptime_seconds: StrictInt = Field(
        ...,
        ge=0,
        description="Mandatory system uptime in seconds",
    )
    temperature: float = Field(
        ...,
        ge=-50.0,
        le=150.0,
        description="Mandatory temperature in Celsius",
    )
    timestamp: datetime = Field(
        ...,
        description="Mandatory ISO 8601 timestamp",
    )
    active_alerts: List[StrictStr] = Field(
        default_factory=list,
        max_length=50,
        description="List of active system alerts",
    )
