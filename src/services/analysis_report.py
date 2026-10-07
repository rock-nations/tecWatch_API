import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from src.models.analysis import AnalysisReport
from src.utils.logger import logger


class AnalysisReportError(Exception):
    """Raised when the configured analysis report is unreadable or fails validation."""
    status_code = 500
    error = "Invalid Analysis Report"

    def __init__(self, detail: str, validation_errors: Optional[List[Dict[str, Any]]] = None):
        super().__init__(detail)
        self.detail = detail
        self.validation_errors = validation_errors or []


class AnalysisReportNotFoundError(AnalysisReportError):
    """Raised when the configured analysis report file does not exist."""
    status_code = 404
    error = "Analysis Report Not Found"


def load_analysis_report(report_path: Path, max_bytes: int) -> Dict[str, Any]:
    """
    Reads the analysis report JSON file and validates it against the AnalysisReport schema.
    Returns the report data exactly as stored in the file.
    """
    logger.info(f"Reading analysis report from: {report_path}")
    try:
        with open(report_path, "rb") as report_file:
            # Read one byte past the limit so oversized reports are detected without loading them fully
            raw_report = report_file.read(max_bytes + 1)
    except FileNotFoundError as e:
        raise AnalysisReportNotFoundError(f"Analysis report file '{report_path.name}' does not exist.") from e
    except OSError as e:
        raise AnalysisReportError(f"Analysis report file '{report_path.name}' could not be read: {e.strerror}.") from e

    # Message length
    if len(raw_report) > max_bytes:
        raise AnalysisReportError(f"Analysis report exceeds the configured size limit ({max_bytes} bytes).")

    # Message format: a UTF-8 encoded JSON object
    try:
        report = json.loads(raw_report)
    except UnicodeDecodeError as e:
        raise AnalysisReportError("Analysis report is not valid UTF-8 encoded JSON.") from e
    except json.JSONDecodeError as e:
        raise AnalysisReportError(f"Malformed JSON syntax at line {e.lineno}, column {e.colno}: {e.msg}") from e
    if not isinstance(report, dict):
        raise AnalysisReportError("Analysis report must be a JSON object containing analysis result fields.")

    # Mandatory fields, data types, field lengths, unexpected content and cross-references
    try:
        AnalysisReport.model_validate(report)
    except ValidationError as e:
        raise AnalysisReportError(
            "Analysis report failed validation (check mandatory fields, data types, message length, or unexpected content).",
            e.errors(),
        ) from e

    return report
