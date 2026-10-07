import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from src.models.analysis import AnalysisReport
from src.models.scenarios import AnalysisScenarios
from src.utils.logger import logger


class AnalysisReportError(Exception):
    """Raised when a configured analysis data file is unreadable or fails validation."""
    status_code = 500

    def __init__(
        self,
        detail: str,
        validation_errors: Optional[List[Dict[str, Any]]] = None,
        error: str = "Invalid Analysis Report",
    ):
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.validation_errors = validation_errors or []


class AnalysisReportNotFoundError(AnalysisReportError):
    """Raised when a configured analysis data file does not exist."""
    status_code = 404

    def __init__(self, detail: str, error: str = "Analysis Report Not Found"):
        super().__init__(detail, error=error)


def load_validated_json(path: Path, max_bytes: int, model: Type[BaseModel], document: str) -> Dict[str, Any]:
    """
    Reads a JSON data file and validates it against the given schema.
    Returns the data exactly as stored in the file. `document` names the file in errors (e.g. "Analysis report").
    """
    title = document.title()
    logger.info(f"Reading {document.lower()} from: {path}")
    try:
        with open(path, "rb") as data_file:
            # Read one byte past the limit so oversized files are detected without loading them fully
            raw_data = data_file.read(max_bytes + 1)
    except FileNotFoundError as e:
        raise AnalysisReportNotFoundError(
            f"{document} file '{path.name}' does not exist.", error=f"{title} Not Found"
        ) from e
    except OSError as e:
        raise AnalysisReportError(
            f"{document} file '{path.name}' could not be read: {e.strerror}.", error=f"Invalid {title}"
        ) from e

    # Message length
    if len(raw_data) > max_bytes:
        raise AnalysisReportError(
            f"{document} exceeds the configured size limit ({max_bytes} bytes).", error=f"Invalid {title}"
        )

    # Message format: a UTF-8 encoded JSON object
    try:
        data = json.loads(raw_data)
    except UnicodeDecodeError as e:
        raise AnalysisReportError(f"{document} is not valid UTF-8 encoded JSON.", error=f"Invalid {title}") from e
    except json.JSONDecodeError as e:
        raise AnalysisReportError(
            f"Malformed JSON syntax at line {e.lineno}, column {e.colno}: {e.msg}", error=f"Invalid {title}"
        ) from e
    if not isinstance(data, dict):
        raise AnalysisReportError(f"{document} must be a JSON object.", error=f"Invalid {title}")

    # Mandatory fields, data types, field lengths, unexpected content and cross-references
    try:
        model.model_validate(data)
    except ValidationError as e:
        raise AnalysisReportError(
            f"{document} failed validation (check mandatory fields, data types, message length, or unexpected content).",
            e.errors(),
            error=f"Invalid {title}",
        ) from e

    return data


def load_analysis_report(report_path: Path, max_bytes: int) -> Dict[str, Any]:
    """Reads and validates the analysis report served by GET /api/analysis."""
    return load_validated_json(report_path, max_bytes, AnalysisReport, "Analysis report")


def load_analysis_scenarios(scenarios_path: Path, max_bytes: int) -> Dict[str, Any]:
    """Reads and validates the analysis scenarios (findings) served by GET /api/analysis/scenarios."""
    return load_validated_json(scenarios_path, max_bytes, AnalysisScenarios, "Analysis scenarios")
