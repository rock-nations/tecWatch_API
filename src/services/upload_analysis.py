"""
Checks the files uploaded to POST /api/analysis/upload and runs the analysis engine on them.
Nothing is stored: the files are analysed in memory and the result is returned to the caller.
"""
import re
import time
from pathlib import PurePath
from typing import Any, Dict, Optional, Tuple

from fastapi import UploadFile
from pydantic import ValidationError

from src.analyzer.capture import CaptureFormatError, is_capture
from src.analyzer.engine import analyze
from src.analyzer.report import ReportFormatError, is_pdf
from src.models.scenarios import AnalysisScenarios
from src.utils.logger import logger

UploadedFile = Tuple[str, bytes]


class UploadAnalysisError(Exception):
    """Raised when an uploaded file is missing, too large, of the wrong type, or cannot be decoded."""

    def __init__(self, status_code: int, error: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


def safe_file_name(name: Optional[str], default: str) -> str:
    """File name without directories or control characters, used in messages and the result."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:120] or default


async def read_upload(upload: Optional[UploadFile], max_bytes: int, default_name: str) -> Optional[UploadedFile]:
    """Reads one uploaded file, at most one byte past the limit so oversized files are detected early."""
    if upload is None:
        return None
    name = safe_file_name(upload.filename, default_name)
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadAnalysisError(
            413, "File Too Large", f"'{name}' exceeds the upload limit of {max_bytes / (1024 * 1024):g} MB."
        )
    if not data:
        if not upload.filename:
            return None  # form field sent without a file
        raise UploadAnalysisError(400, "Empty File", f"'{name}' is empty.")
    return name, data


def check_upload_types(capture: Optional[UploadedFile], report: Optional[UploadedFile]) -> None:
    """At least one file is required; each file must match its field (checked by content, not by extension)."""
    if capture is None and report is None:
        raise UploadAnalysisError(
            400, "No File Uploaded", "Upload a capture (.pcapng or .pcap) and/or a CANoe test report (.pdf)."
        )
    if capture is not None and not is_capture(capture[1]):
        hint = " It is a PDF document - upload it as the test report." if is_pdf(capture[1]) else ""
        raise UploadAnalysisError(
            415, "Unsupported File Type", f"'{capture[0]}' is not a pcapng or pcap capture file.{hint}"
        )
    if report is not None and not is_pdf(report[1]):
        hint = " It is a capture file - upload it as the capture." if is_capture(report[1]) else ""
        raise UploadAnalysisError(415, "Unsupported File Type", f"'{report[0]}' is not a PDF document.{hint}")


def run_upload_analysis(capture: Optional[UploadedFile], report: Optional[UploadedFile]) -> Dict[str, Any]:
    """Runs the analysis engine (blocking; call it in a worker thread) and validates its result."""
    started = time.perf_counter()
    try:
        document = analyze(capture, report)
    except CaptureFormatError as e:
        raise UploadAnalysisError(422, "Unreadable Capture", f"'{capture[0]}' could not be decoded: {e}") from e
    except ReportFormatError as e:
        raise UploadAnalysisError(422, "Unreadable Test Report", f"'{report[0]}' could not be read: {e}") from e
    except Exception as e:
        logger.exception("Upload analysis failed")
        raise UploadAnalysisError(500, "Analysis Failed", "The uploaded files could not be analysed.") from e

    try:
        AnalysisScenarios.model_validate(document)
    except ValidationError as e:
        logger.error(f"Upload analysis produced an invalid result: {e}")
        raise UploadAnalysisError(500, "Analysis Failed", "The analysis result failed validation.") from e

    files = ", ".join(f"{name} ({len(data)} bytes)" for name, data in filter(None, (capture, report)))
    logger.info(
        f"Upload analysis of {files}: {len(document['scenarios'])} findings, {len(document['test_cases'])} test cases "
        f"in {(time.perf_counter() - started) * 1000:.0f} ms"
    )
    return document
