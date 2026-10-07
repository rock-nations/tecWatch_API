"""
Parser for CANoe test reports exported as PDF (Vector Test Report Viewer).
Text is extracted with pypdf in layout mode; the parser works on the text lines, so it can be
unit-tested without PDF files.
"""
import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

VERDICTS = ("Pass", "Fail", "Inconclusive", "None", "Error in test system")
_VERDICT_PATTERN = "|".join(re.escape(v) for v in VERDICTS)

TIMESTAMP_LINE = re.compile(r"^\s*(\d+\.\d{3,})\s{2,}(.*)$")
TEST_CASE_LINE = re.compile(
    rf"^\s*(\d+\.\d+)\s+(\d+)\.\s+(\S+?)(?:\(([^)]*)\))?\s+({_VERDICT_PATTERN})\s*$"
)
VERDICT_AT_END = re.compile(rf"^(.*?)\s{{2,}}({_VERDICT_PATTERN})\s*$")
GROUP_LINE = re.compile(r"\[\d+ \.\. \d+\]")
SENT_COMMAND = re.compile(r"\bSende\s+'([^']+)'")
NOISE_LINES = {"reason", "completion", "preparation", "main part", "wait"}
MAX_REPORT_PAGES = 400


class ReportFormatError(ValueError):
    """Raised when the uploaded file is not a readable CANoe test report PDF."""


@dataclass
class ReportFailure:
    canoe_time_s: Optional[float]
    step: Optional[str]
    text: str
    verdict: str


@dataclass
class ReportTestCase:
    number: int
    test_case_id: str
    variant: Optional[str]
    verdict: str
    start_s: float
    end_s: float = 0.0
    failures: List[ReportFailure] = field(default_factory=list)
    failed_sections: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"TC{self.number} {self.test_case_id}"


@dataclass
class TestReport:
    test_unit: Optional[str] = None
    verdict: Optional[str] = None
    begin: Optional[str] = None
    end: Optional[str] = None
    utc_offset: Optional[str] = None
    configuration: Optional[str] = None
    canoe_version: Optional[str] = None
    computer: Optional[str] = None
    incomplete: bool = False
    test_cases: List[ReportTestCase] = field(default_factory=list)
    failures: List[ReportFailure] = field(default_factory=list)
    sent_commands: List[Tuple[float, str]] = field(default_factory=list)  # telegrams the test script sent ("Sende '...'")
    last_time_s: float = 0.0

    def test_case_at(self, canoe_time_s: Optional[float]) -> Optional[ReportTestCase]:
        if canoe_time_s is None:
            return None
        for index, test_case in enumerate(self.test_cases):
            is_last = index == len(self.test_cases) - 1
            if test_case.start_s <= canoe_time_s and (canoe_time_s < test_case.end_s or (is_last and canoe_time_s <= test_case.end_s)):
                return test_case
        return None


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def extract_pages(pdf_bytes: bytes) -> List[List[str]]:
    """Returns the text lines of every page (pypdf layout mode keeps table columns on one line)."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
    except Exception as e:  # pypdf raises many exception types for damaged files
        raise ReportFormatError(f"The PDF could not be read ({e}).") from e
    if page_count > MAX_REPORT_PAGES:
        raise ReportFormatError(f"The report has {page_count} pages; at most {MAX_REPORT_PAGES} pages are supported.")
    try:
        # pages without a content stream have no text (pypdf's layout mode fails on them)
        return [(page.extract_text(extraction_mode="layout") or "").splitlines() if "/Contents" in page else []
                for page in reader.pages]
    except Exception as e:
        raise ReportFormatError(f"The text of the PDF could not be extracted ({e}).") from e


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _columns(line: str) -> List[str]:
    return [column for column in re.split(r"\s{2,}", line.strip()) if column]


def _is_continuation(line: str) -> bool:
    """A wrapped tail of a long report line (pypdf lists each page bottom-up, so it precedes its line)."""
    text = _clean(line)
    if len(text) < 3 or TIMESTAMP_LINE.match(line) or VERDICT_AT_END.match(line):
        return False
    lowered = text.lower()
    if lowered in NOISE_LINES or lowered.startswith(("reason", "time stamp")) or lowered.endswith((" pass", " fail")):
        return False
    return not GROUP_LINE.search(text)


def parse_report(pages: List[List[str]]) -> TestReport:
    report = TestReport()
    lines = [line for page in pages for line in page]
    seen_numbers = set()

    for line in lines:
        text = _clean(line)
        if report.test_unit is None and (match := re.match(r"^Test Configuration:\s+(.+)$", text)):
            report.test_unit = match.group(1)
        elif report.begin is None and (match := re.match(r"^Test (?:Unit )?Begin:\s+(.+)$", text)):
            report.begin = match.group(1)
            offset = re.search(r"([+-]\d{2}:\d{2})$", report.begin)
            report.utc_offset = offset.group(1) if offset else None
        elif report.end is None and (match := re.match(r"^Test (?:Unit )?End:\s+(.+)$", text)):
            report.end = match.group(1)
        elif report.canoe_version is None and (match := re.match(r"^Version:\s+(CANoe\S*.*)$", text)):
            report.canoe_version = match.group(1)
        elif report.computer is None and (match := re.match(r"^Computer Name:\s+(.+)$", text)):
            report.computer = match.group(1)
        if report.configuration is None and (match := re.search(r"([\w.-]+\.cfg)\b", text)):
            report.configuration = match.group(1)
        if "Test is incomplete" in text:
            report.incomplete = True
        if report.verdict is None and report.test_unit and text.startswith(report.test_unit + " ") and GROUP_LINE.search(text):
            match = VERDICT_AT_END.match(line)
            report.verdict = match.group(2) if match else None

        match = TEST_CASE_LINE.match(line)
        if match and int(match.group(2)) not in seen_numbers:
            seen_numbers.add(int(match.group(2)))
            report.test_cases.append(ReportTestCase(
                number=int(match.group(2)),
                test_case_id=match.group(3),
                variant=match.group(4),
                verdict=match.group(5),
                start_s=float(match.group(1)),
            ))
        timestamp = TIMESTAMP_LINE.match(line)
        if timestamp:
            report.last_time_s = max(report.last_time_s, float(timestamp.group(1)))
            sent = SENT_COMMAND.search(timestamp.group(2))
            if sent:
                report.sent_commands.append((float(timestamp.group(1)), _clean(sent.group(1))))

    report.test_cases.sort(key=lambda tc: tc.start_s)
    report.sent_commands.sort()
    for current, following in zip(report.test_cases, report.test_cases[1:] + [None]):
        current.end_s = following.start_s if following else max(report.last_time_s, current.start_s)

    for page in pages:
        for index, line in enumerate(page):
            verdict = VERDICT_AT_END.match(line)
            if not verdict or verdict.group(2) not in ("Fail", "Inconclusive") or TEST_CASE_LINE.match(line):
                continue
            timestamp = TIMESTAMP_LINE.match(line)
            if timestamp:
                columns = _columns(timestamp.group(2))[:-1]  # drop the verdict column
                step = columns[0] if len(columns) > 1 and " " not in columns[0] and len(columns[0]) <= 16 else None
                text = _clean(" ".join(columns[1:] if step else columns))
                if GROUP_LINE.search(text):
                    continue  # verdict of a test group (e.g. "Test Fixture [1 .. 5]"), not a failing step
                if index > 0 and not text.endswith((".", "!", ")")) and _is_continuation(page[index - 1]):
                    text = f"{text} {_clean(page[index - 1])}"
                failure = ReportFailure(float(timestamp.group(1)), step, text, verdict.group(2))
                report.failures.append(failure)
                test_case = report.test_case_at(failure.canoe_time_s)
                if test_case:
                    test_case.failures.append(failure)
            else:
                title = _clean(verdict.group(1))
                if (GROUP_LINE.search(title) or title.lower().startswith(("time stamp", "test fixture"))
                        or any(tc.test_case_id in title for tc in report.test_cases)):
                    continue
                test_case = report.test_case_at(_nearest_time(page, index))
                if test_case and title not in test_case.failed_sections:
                    test_case.failed_sections.append(title)

    for test_case in report.test_cases:
        test_case.failures.sort(key=lambda f: f.canoe_time_s or 0.0)
    report.failures.sort(key=lambda f: f.canoe_time_s or 0.0)
    return report


def _nearest_time(page: List[str], index: int) -> Optional[float]:
    """Time of the closest timestamped line, preferring the step lines listed above a section title."""
    for distance in range(1, 15):
        for candidate in (index - distance, index + distance):
            if 0 <= candidate < len(page):
                match = TIMESTAMP_LINE.match(page[candidate])
                if match:
                    return float(match.group(1))
    return None


def read_report(pdf_bytes: bytes) -> TestReport:
    if not is_pdf(pdf_bytes):
        raise ReportFormatError("The file is not a PDF document.")
    report = parse_report(extract_pages(pdf_bytes))
    if not report.test_cases:
        raise ReportFormatError("No test cases found - is this a CANoe test report?")
    return report
