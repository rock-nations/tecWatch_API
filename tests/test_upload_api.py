import io
import pytest
import defusedxml.ElementTree as DefusedET
from pypdf import PdfWriter
from config.settings import ConfigManager
from src.models.scenarios import AnalysisScenarios
from tests.sample_files import REAL_CAPTURE, REAL_REPORT, disturbed_capture

UPLOAD = "/api/analysis/upload"
PCAPNG = "application/vnd.tcpdump.pcap"


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _assert_error(response, status, error, fragment):
    assert response.status_code == status, response.text
    data = response.json()
    assert data["error"] == error
    assert fragment in data["detail"], data["detail"]


@pytest.mark.asyncio
async def test_upload_capture_only(client):
    response = await client.post(UPLOAD, files={"capture": ("bench trace.pcapng", disturbed_capture(), PCAPNG)})
    assert response.status_code == 200, response.text
    data = response.json()
    AnalysisScenarios.model_validate(data)
    assert data["source_file"] == "bench trace.pcapng"
    assert data["test_cases"] == []
    titles = [s["title"] for s in data["scenarios"]]
    assert any("became 'gestört'" in title for title in titles)
    assert titles[-1].startswith("Communication layer ruled out")


@pytest.mark.asyncio
async def test_upload_returns_xml_on_request(client):
    response = await client.post(
        UPLOAD, files={"capture": ("trace.pcapng", disturbed_capture(), PCAPNG)}, headers={"Accept": "application/xml"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    root = DefusedET.fromstring(response.content)
    assert root.tag == "AnalysisScenarios"
    assert root.find("scenarios/id").text == "S01"


@pytest.mark.asyncio
async def test_upload_strips_directories_from_file_names(client):
    response = await client.post(UPLOAD, files={"capture": ("C:\\bench\\run 7.pcapng", disturbed_capture(), PCAPNG)})
    assert response.status_code == 200
    assert response.json()["source_file"] == "run 7.pcapng"


@pytest.mark.asyncio
async def test_upload_without_files(client):
    _assert_error(await client.post(UPLOAD, data={"note": "x"}), 400, "No File Uploaded", "Upload a capture")
    _assert_error(await client.post(UPLOAD), 400, "No File Uploaded", "and/or a CANoe test report")


@pytest.mark.asyncio
async def test_upload_empty_file(client):
    response = await client.post(UPLOAD, files={"capture": ("trace.pcapng", b"", PCAPNG)})
    _assert_error(response, 400, "Empty File", "'trace.pcapng' is empty")


@pytest.mark.asyncio
async def test_upload_files_in_the_wrong_fields(client):
    response = await client.post(UPLOAD, files={"capture": ("report.pdf", _blank_pdf(), "application/pdf")})
    _assert_error(response, 415, "Unsupported File Type", "upload it as the test report")

    response = await client.post(UPLOAD, files={"report": ("trace.pcapng", disturbed_capture(), "application/pdf")})
    _assert_error(response, 415, "Unsupported File Type", "upload it as the capture")

    response = await client.post(UPLOAD, files={"report": ("notes.txt", b"just text", "text/plain")})
    _assert_error(response, 415, "Unsupported File Type", "'notes.txt' is not a PDF document.")


@pytest.mark.asyncio
async def test_upload_damaged_capture(client):
    damaged = disturbed_capture()[:200] + b"\xff" * 64
    response = await client.post(UPLOAD, files={"capture": ("trace.pcapng", damaged, PCAPNG)})
    _assert_error(response, 422, "Unreadable Capture", "'trace.pcapng' could not be decoded")


@pytest.mark.asyncio
async def test_upload_pdf_that_is_no_test_report(client):
    response = await client.post(UPLOAD, files={"report": ("invoice.pdf", _blank_pdf(), "application/pdf")})
    _assert_error(response, 422, "Unreadable Test Report", "No test cases found")

    response = await client.post(UPLOAD, files={"report": ("broken.pdf", b"%PDF-1.4 broken", "application/pdf")})
    _assert_error(response, 422, "Unreadable Test Report", "'broken.pdf' could not be read")


@pytest.mark.asyncio
async def test_upload_file_too_large(client):
    ConfigManager.get_instance().config.analysis.max_upload_bytes = 2048
    response = await client.post(UPLOAD, files={"capture": ("trace.pcapng", disturbed_capture(), PCAPNG)})
    _assert_error(response, 413, "File Too Large", "exceeds the upload limit")


@pytest.mark.asyncio
async def test_upload_has_its_own_request_size_limit(client):
    # 1.5 MB is above the 1 MB limit of the other endpoints but within the upload limit
    capture = disturbed_capture(custom_block=b"\x00" * 1_500_000)
    response = await client.post(UPLOAD, files={"capture": ("big.pcapng", capture, PCAPNG)})
    assert response.status_code == 200, response.text

    ConfigManager.get_instance().config.analysis.max_upload_bytes = 512 * 1024
    response = await client.post(UPLOAD, files={"capture": ("big.pcapng", capture, PCAPNG)})
    assert response.status_code == 413
    assert response.json()["error"] == "Payload Too Large"


@pytest.mark.asyncio
async def test_other_endpoints_keep_the_payload_limit(client):
    response = await client.post(
        "/api/analysis", content=b"{" + b" " * 1_100_000 + b"}", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.skipif(not (REAL_CAPTURE.exists() and REAL_REPORT.exists()), reason="test-bench files not available")
async def test_upload_real_test_bench_files(client):
    response = await client.post(UPLOAD, files={
        "capture": (REAL_CAPTURE.name, REAL_CAPTURE.read_bytes(), PCAPNG),
        "report": (REAL_REPORT.name, REAL_REPORT.read_bytes(), "application/pdf"),
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["test_run"]["overall_verdict"].startswith("FAIL – 2 Pass, 2 Fail, 1 Inconclusive")
    assert [tc["verdict"] for tc in data["test_cases"]] == ["Pass", "Pass", "Fail", "Fail", "Inconclusive"]
    assert data["scenarios"][0]["title"] == "GFM-A 34W1 became 'gestört' 102 ms after an occupation without a valid axle count"
