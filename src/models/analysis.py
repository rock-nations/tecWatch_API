from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class DataComparison(BaseModel):
    """Represents a row in the frontend Data-Structure Comparison View."""
    model_config = ConfigDict(extra="forbid")

    field: StrictStr = Field(..., min_length=1, max_length=64, description="Field name (e.g. MessageID, Length)")
    expected: StrictStr = Field(..., description="Expected value representation")
    actual: StrictStr = Field(..., description="Actual observed value representation")
    result: StrictStr = Field(..., min_length=1, max_length=32, description="Comparison outcome (e.g. OK, Error)")


class FailureFinding(BaseModel):
    """Represents an item in the frontend Failure Analysis View."""
    model_config = ConfigDict(extra="forbid")

    message_id: StrictStr = Field(..., min_length=1, max_length=64, description="Identifier of the message")
    expected_length: int = Field(..., ge=0, description="Expected message length in bytes")
    actual_length: int = Field(..., ge=0, description="Actual observed message length in bytes")
    result: StrictStr = Field(..., min_length=1, max_length=64, description="Failure diagnostic (e.g. Message Length Error)")

    from pydantic import field_validator

    @field_validator("expected_length", "actual_length", mode="before")
    @classmethod
    def parse_int_from_str(cls, v):
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return v


class TraceMessage(BaseModel):
    """Represents an individual message in the frontend Trace-Data View."""
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(..., description="Message capture timestamp")
    sender: StrictStr = Field(..., min_length=1, max_length=64, description="Sender node/address")
    receiver: StrictStr = Field(..., min_length=1, max_length=64, description="Receiver node/address")
    protocol: StrictStr = Field(..., min_length=1, max_length=32, description="Protocol (e.g. CAN, ETHERNET, TCP, MODBUS)")
    message_type: StrictStr = Field(..., min_length=1, max_length=64, description="Message type (e.g. TELEMETRY, HEARTBEAT)")
    status: StrictStr = Field(..., min_length=1, max_length=32, description="Status (e.g. OK, FAILED, WARNING)")
    error_reason: Optional[StrictStr] = Field(default=None, max_length=256, description="Specific error reason if failed")


class AnalysisResultRequest(BaseModel):
    """Full trace-analysis result submitted by analysis components or upstream tecWatch."""
    model_config = ConfigDict(extra="forbid")

    analysis_id: StrictStr = Field(..., min_length=3, max_length=64, description="Unique analysis run ID")
    device_id: StrictStr = Field(..., min_length=1, max_length=64, description="Device under test / monitored")
    timestamp: datetime = Field(..., description="Analysis execution timestamp")
    analysis_type: StrictStr = Field(..., min_length=2, max_length=64, description="Type of analysis (e.g. TRACE_COMMUNICATION)")
    result_status: StrictStr = Field(..., min_length=2, max_length=32, description="Overall outcome (e.g. PASSED, FAILED)")
    summary: StrictStr = Field(..., min_length=1, max_length=1024, description="Executive summary of findings")
    trace_messages: List[TraceMessage] = Field(default_factory=list, description="List of trace messages for Trace-Data View")
    failure_findings: List[FailureFinding] = Field(default_factory=list, description="Identified failures for Failure-Analysis View")
    data_comparisons: List[DataComparison] = Field(default_factory=list, description="Field comparisons for Comparison View")

    from pydantic import field_validator

    @field_validator("trace_messages", "failure_findings", "data_comparisons", mode="before")
    @classmethod
    def ensure_list(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, dict):
            return [v]
        return v



class AnalysisResultResponse(BaseModel):
    """Acknowledgment returned upon accepting an analysis payload."""
    model_config = ConfigDict(extra="forbid")

    status: StrictStr = Field(..., description="Response status (e.g. SUCCESS)")
    message: StrictStr = Field(..., description="Acknowledgment message")
    analysis_id: StrictStr = Field(..., description="Target analysis ID")
    processed_at: datetime = Field(..., description="Timestamp of acknowledgment")
