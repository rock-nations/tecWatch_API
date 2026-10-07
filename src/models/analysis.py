from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    StrictStr,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)


def _is_xml(info: ValidationInfo) -> bool:
    """XML payloads are validated with context {"source_format": "xml"} (see routes.post_analysis)."""
    return bool(info.context) and info.context.get("source_format") == "xml"


def _xml_empty_to_none(value: Any, info: ValidationInfo) -> Any:
    # An empty XML element (<test_case/>) is how XML writes null
    if _is_xml(info) and value == "":
        return None
    return value


def _xml_to_list(value: Any, info: ValidationInfo) -> Any:
    # XML has no arrays: a single child element arrives as one value, no child elements as ""
    if not _is_xml(info) or isinstance(value, list):
        return value
    return [] if value == "" else [value]


def _reject_numeric_timestamp(value: Any) -> Any:
    # Lax datetime parsing would accept Unix epoch numbers; the report format uses ISO 8601 strings
    if isinstance(value, (int, float)):
        raise ValueError("timestamp must be an ISO 8601 date-time string")
    return value


IsoTimestamp = Annotated[datetime, Strict(False), BeforeValidator(_reject_numeric_timestamp)]
FieldName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
FieldValue = Union[bool, int, float, Annotated[str, StringConstraints(max_length=256)], None]
EvidenceItem = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    """
    Strict base model: JSON values must already have the declared type ("47" is not an integer)
    and undeclared keys are rejected. XML input is validated with strict=False, since XML text
    carries no data types.
    """
    model_config = ConfigDict(extra="forbid", strict=True)


class TraceMessage(StrictModel):
    """Represents a decoded telegram in the frontend Trace-Data View."""

    message_id: str = Field(..., min_length=1, max_length=64, description="Unique message identifier (e.g. frame-380-2)")
    timestamp: IsoTimestamp = Field(..., description="Message capture timestamp")
    time_s: float = Field(..., ge=0, description="Seconds since the start of the trace")
    sender: str = Field(..., min_length=1, max_length=64, description="Sender node/address")
    receiver: str = Field(..., min_length=1, max_length=64, description="Receiver node/address")
    protocol: str = Field(..., min_length=1, max_length=64, description="Protocol (e.g. SCI-TDS BL5 over RaSTA)")
    message_type: str = Field(..., min_length=1, max_length=64, description="Telegram type (e.g. MELDUNG_GFMA_BELEGUNGSZUSTAND)")
    message_code: str = Field(..., pattern=r"^0x[0-9A-Fa-f]{1,8}$", description="Hexadecimal telegram code (e.g. 0x0007)")
    direction: str = Field(..., min_length=1, max_length=32, description="Transfer direction (e.g. AZ→ZE)")
    length: int = Field(..., ge=0, description="Telegram length in bytes")
    fields: Dict[FieldName, FieldValue] = Field(default_factory=dict, description="Decoded telegram fields")
    test_case: Optional[str] = Field(default=None, min_length=1, max_length=64, description="Test case the message belongs to")
    status: Literal["OK", "FAILED", "WARNING"] = Field(..., description="Message verdict")
    error_reason: Optional[str] = Field(default=None, min_length=1, max_length=256, description="Specific error reason if not OK")

    @field_validator("test_case", "error_reason", mode="before")
    @classmethod
    def xml_nulls(cls, value: Any, info: ValidationInfo) -> Any:
        return _xml_empty_to_none(value, info)

    @field_validator("fields", mode="before")
    @classmethod
    def xml_empty_fields(cls, value: Any, info: ValidationInfo) -> Any:
        return {} if _is_xml(info) and value == "" else value


class FailureFinding(StrictModel):
    """Represents an item in the frontend Failure-Analysis View."""

    message_id: Optional[str] = Field(default=None, min_length=1, max_length=64, description="Referenced trace message (null if no single message applies)")
    expected_length: Optional[int] = Field(default=None, ge=0, description="Expected message length in bytes")
    actual_length: Optional[int] = Field(default=None, ge=0, description="Actual observed message length in bytes")
    result: str = Field(..., min_length=1, max_length=64, description="Failure diagnostic (e.g. Message Length Error)")
    test_case: Optional[str] = Field(default=None, min_length=1, max_length=64, description="Affected test case")
    timestamp: IsoTimestamp = Field(..., description="Time of the failure")
    time_s: float = Field(..., ge=0, description="Seconds since the start of the trace")
    category: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,63}$", description="Root-cause category (e.g. incorrect_length)")
    description: str = Field(..., min_length=1, max_length=1024, description="Explanation of the failure")
    confidence: float = Field(..., ge=0, le=1, description="Confidence of the finding (0.0 - 1.0)")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="Trace/report locations supporting the finding")

    @field_validator("message_id", "expected_length", "actual_length", "test_case", mode="before")
    @classmethod
    def xml_nulls(cls, value: Any, info: ValidationInfo) -> Any:
        return _xml_empty_to_none(value, info)

    @field_validator("evidence", mode="before")
    @classmethod
    def xml_evidence_list(cls, value: Any, info: ValidationInfo) -> Any:
        return _xml_to_list(value, info)

    @model_validator(mode="after")
    def lengths_come_in_pairs(self) -> "FailureFinding":
        if (self.expected_length is None) != (self.actual_length is None):
            raise ValueError("expected_length and actual_length must both be set or both be null")
        return self


class DataComparison(StrictModel):
    """Represents a row in the frontend Data-Structure Comparison View."""

    field: str = Field(..., min_length=1, max_length=128, description="Compared field (e.g. Test verdict)")
    expected: str = Field(..., max_length=256, description="Expected value representation")
    actual: str = Field(..., max_length=256, description="Actual observed value representation")
    result: Literal["OK", "Error", "Warning"] = Field(..., description="Comparison outcome")
    test_case: Optional[str] = Field(default=None, min_length=1, max_length=64, description="Test case (null for trace-wide checks)")

    @field_validator("test_case", mode="before")
    @classmethod
    def xml_nulls(cls, value: Any, info: ValidationInfo) -> Any:
        return _xml_empty_to_none(value, info)


class AnalysisReport(StrictModel):
    """
    Trace-analysis report: served by GET /api/analysis from the configured report file
    and accepted by POST /api/analysis from analysis components.
    """

    analysis_id: str = Field(..., min_length=3, max_length=64, description="Unique analysis run ID")
    device_id: str = Field(..., min_length=1, max_length=64, description="Device under test / monitored")
    timestamp: IsoTimestamp = Field(..., description="Analysis execution timestamp")
    analysis_type: str = Field(..., min_length=2, max_length=64, description="Type of analysis (e.g. TRACE_COMMUNICATION)")
    result_status: Literal["PASSED", "FAILED", "WARNING", "INCONCLUSIVE"] = Field(..., description="Overall outcome")
    summary: str = Field(..., min_length=1, max_length=4096, description="Executive summary of findings")
    trace_messages: List[TraceMessage] = Field(default_factory=list, description="List of trace messages for Trace-Data View")
    failure_findings: List[FailureFinding] = Field(default_factory=list, description="Identified failures for Failure-Analysis View")
    data_comparisons: List[DataComparison] = Field(default_factory=list, description="Field comparisons for Comparison View")

    @field_validator("trace_messages", "failure_findings", "data_comparisons", mode="before")
    @classmethod
    def xml_lists(cls, value: Any, info: ValidationInfo) -> Any:
        return _xml_to_list(value, info)

    @field_validator("trace_messages")
    @classmethod
    def message_ids_unique(cls, messages: List[TraceMessage]) -> List[TraceMessage]:
        seen = set()
        duplicates = []
        for message in messages:
            if message.message_id in seen and message.message_id not in duplicates:
                duplicates.append(message.message_id)
            seen.add(message.message_id)
        if duplicates:
            raise ValueError(f"message_id must be unique; duplicated: {', '.join(duplicates)}")
        return messages

    @field_validator("failure_findings")
    @classmethod
    def findings_match_trace_messages(cls, findings: List[FailureFinding], info: ValidationInfo) -> List[FailureFinding]:
        messages = info.data.get("trace_messages")
        if messages is None:
            # trace_messages is invalid itself and already reported
            return findings

        message_lengths = {message.message_id: message.length for message in messages}
        problems = []
        for index, finding in enumerate(findings):
            if finding.message_id is None:
                continue
            if finding.message_id not in message_lengths:
                problems.append(
                    f"failure_findings[{index}].message_id '{finding.message_id}' does not match any trace message"
                )
            elif finding.actual_length is not None and finding.actual_length != message_lengths[finding.message_id]:
                problems.append(
                    f"failure_findings[{index}].actual_length {finding.actual_length} differs from the "
                    f"length {message_lengths[finding.message_id]} of trace message '{finding.message_id}'"
                )
        if problems:
            raise ValueError("; ".join(problems))
        return findings


class AnalysisResultResponse(BaseModel):
    """Acknowledgment returned upon accepting an analysis payload."""
    model_config = ConfigDict(extra="forbid")

    status: StrictStr = Field(..., description="Response status (e.g. SUCCESS)")
    message: StrictStr = Field(..., description="Acknowledgment message")
    analysis_id: StrictStr = Field(..., description="Target analysis ID")
    processed_at: datetime = Field(..., description="Timestamp of acknowledgment")
