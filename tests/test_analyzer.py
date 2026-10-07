import struct
import pytest
from src.analyzer import engine
from src.analyzer.capture import CaptureFormatError, decode_udp, read_packets
from src.analyzer.engine import analyze, decode_capture
from src.analyzer.report import ReportFormatError, parse_report, read_report
from src.analyzer.sci import decode_rasta, decode_sci
from src.models.scenarios import AnalysisScenarios
from tests.sample_files import (
    BELEGT,
    CANOE_OFFSET_S,
    CAPTURE_START,
    GESTOERT,
    OC_IP,
    REAL_CAPTURE,
    REAL_REPORT,
    SECTION,
    ZE_IP,
    CaptureBuilder,
    disturbed_capture,
    gfma_state,
    icmp_port_unreachable,
    pcap,
    rasta,
    report_pages,
    sci,
    udp_frame,
)


@pytest.fixture
def synthetic_report(monkeypatch):
    """Lets analyze() read the synthetic report text instead of a PDF."""
    monkeypatch.setattr(engine, "read_report", lambda data: parse_report(report_pages()))
    return ("Report.pdf", b"%PDF-1.7 synthetic")


def _finding(document, fragment):
    matches = [s for s in document["scenarios"] if fragment in s["title"]]
    assert matches, [s["title"] for s in document["scenarios"]]
    return matches[0]


# --- capture reader --------------------------------------------------------------------------------

def test_pcapng_frames_are_numbered_like_wireshark():
    data = disturbed_capture(custom_block=b"<CANoe pcaplog metadata/>")
    packets = read_packets(data)
    # the Custom Block counts as frame 1 (without data), the first RaSTA PDU is frame 2
    assert packets[0].number == 2
    assert packets[0].timestamp == pytest.approx(CAPTURE_START)
    udp = decode_udp(packets[0])
    assert (udp.src, udp.dst, udp.dst_port) == (ZE_IP, OC_IP, 24001)


def test_classic_pcap_and_untagged_ethernet():
    frame = udp_frame(ZE_IP, OC_IP, b"hello", vlan=None)
    packets = read_packets(pcap([(CAPTURE_START + 1.25, frame)]))
    assert packets[0].number == 1
    assert packets[0].timestamp == pytest.approx(CAPTURE_START + 1.25)
    assert decode_udp(packets[0]).payload == b"hello"


@pytest.mark.parametrize("data", [b"not a capture at all, just text", b"\x0a\x0d\x0d\x0a" + b"\xff" * 40])
def test_unreadable_capture_raises(data):
    with pytest.raises(CaptureFormatError):
        read_packets(data)


# --- RaSTA / SCI-TDS decoding -------------------------------------------------------------------------

def test_decode_rasta_data_pdu_with_gfma_state():
    pdu = decode_rasta(rasta(6240, 7, 123456, messages=[gfma_state(GESTOERT, 1, 0x0002)]))
    assert (pdu.pdu_type, pdu.seq, pdu.timestamp, pdu.type_name) == (6240, 7, 123456, "Data")
    telegram = decode_sci(pdu.messages[0])
    assert telegram.protocol == "TDS"
    assert telegram.sender == SECTION
    assert telegram.fields["belegung_text"] == "gestört"
    assert telegram.fields["grundstellbar_text"] == "grundst."
    assert telegram.fields["achszaehlfuellstand"] == 2
    assert telegram.describe() == "Meldung GFM-A Belegungszustand(0x0007) [gestört, grundst.]"


def test_decode_rasta_connection_and_disconnect():
    assert decode_rasta(rasta(6200, 0, 1, b"0303" + b"\x00" * 10)).version == "0303"
    assert decode_rasta(rasta(6216, 9, 1, struct.pack("<HH", 0, 4))).disconnect_reason == 4


def test_non_rasta_payload_is_ignored():
    assert decode_rasta(b"\x00" * 40) is None
    assert decode_rasta(b"short") is None
    assert decode_sci(b"\x77" + b"\x00" * 50) is None


# --- report parser ------------------------------------------------------------------------------------

def test_parse_report_text():
    report = parse_report(report_pages())
    assert (report.test_unit, report.verdict, report.utc_offset, report.incomplete) == ("TDS-Test", "Fail", "+02:00", True)
    assert report.configuration == "ZE_RealOC_Stimulation.cfg"
    assert [(tc.number, tc.verdict, tc.start_s, tc.end_s) for tc in report.test_cases] == [
        (1, "Pass", 3.7, 6.0), (2, "Fail", 6.0, 26.0), (3, "Inconclusive", 26.0, 27.5),
    ]
    tc2 = report.test_cases[1]
    assert tc2.variant == "F-ReZE"
    # the wrapped tail of the failing step (listed above it) is joined to its text
    assert tc2.failures[0].text.endswith("Belegungszustand=3, Grundstellungsfaehigkeit=0.")
    assert tc2.failures[0].step == "Init"
    assert tc2.failed_sections[0] == "GFM-A manuell vorbereiten; bei Bedarf vorbereitende AZGH"
    assert [f.canoe_time_s for f in report.test_cases[2].failures] == [26.8, 27.5]
    assert [t for t, _ in report.sent_commands] == [4.5, 25.0]


def test_read_report_rejects_non_pdf_and_reports_without_test_cases():
    with pytest.raises(ReportFormatError, match="not a PDF"):
        read_report(b"plain text")
    with pytest.raises(ReportFormatError):
        read_report(b"%PDF-1.4 damaged")


# --- engine ---------------------------------------------------------------------------------------------

def test_capture_time_is_aligned_with_canoe_time():
    capture = decode_capture("trace.pcapng", disturbed_capture(), None)
    assert capture.offset_s == pytest.approx(CANOE_OFFSET_S, abs=1e-6)
    assert (capture.ze_ip, capture.oc_ip, capture.port) == (ZE_IP, OC_IP, 24001)
    assert len(capture.sessions) == 1  # the heartbeat after the disconnect is no new session
    gestoert = [s for s in capture.states if s.occupancy == GESTOERT]
    assert gestoert[0].time_s == pytest.approx(5.1 + CANOE_OFFSET_S)


def test_trace_only_analysis():
    document = analyze(("trace.pcapng", disturbed_capture()), None)
    AnalysisScenarios.model_validate(document)
    assert document["test_cases"] == []
    assert document["test_run"]["overall_verdict"].startswith("Trace analysis only")

    disturbance = _finding(document, "became 'gestört' 100 ms after an occupation without a valid axle count")
    assert disturbance["severity"] == "Medium"  # no test report, short episode
    assert any("0x0000 (INVALID)" in line for line in disturbance["evidence"])
    assert _finding(document, "discarded silently")["severity"] == "Medium"
    assert _finding(document, "while GFM-A was 'gestört' and not 'grundstellbar'")
    healthy = _finding(document, "Communication layer ruled out")
    assert healthy["severity"] == "Info" and healthy["applies_to_all_test_cases"]

    states = document["gfma_state_history"]["states"]
    assert [s["occupancy"] for s in states] == ["frei", "belegt", "gestört"]
    assert states[-1]["duration_note"].startswith("until end of capture")


def test_combined_analysis_explains_failed_test_cases(synthetic_report):
    document = analyze(("trace.pcapng", disturbed_capture()), synthetic_report)
    AnalysisScenarios.model_validate(document)
    assert document["test_run"]["overall_verdict"] == (
        "FAIL – 1 Pass, 1 Fail, 1 Inconclusive; test unit stopped manually (incomplete)"
    )

    tc1, tc2, tc3 = document["test_cases"]
    assert tc1["root_cause"].startswith("Passed")
    assert tc2["failure_point"] == "GFM-A manuell vorbereiten; bei Bedarf vorbereitende AZGH – preparation, 24.000 s"
    assert "switched to 'gestört' at 8.600 s, 100 ms after an occupation with an invalid axle count" in tc2["root_cause"]
    assert "AZGH sent manually from the panel (not by the test script) was discarded" in tc2["root_cause"]
    assert "timed out after 15 s" in tc2["root_cause"]
    assert "stopped the test unit manually" in tc3["root_cause"]

    disturbance = _finding(document, "became 'gestört'")
    assert disturbance["severity"] == "High"  # a test step failed while the section was disturbed
    assert disturbance["id"] == "S01"
    assert disturbance["id"] in tc2["scenario_ids"]
    assert _finding(document, "not sent by the test script")["test_cases"] == ["TC_NPRO.295.00525.01"]
    assert _finding(document, "Preparation timed out")["severity"] == "High"
    assert _finding(document, "stopped manually")["severity"] == "Low"

    # the timeline merges capture and report events in CANoe time
    sources = {event["source"] for event in document["timeline"]}
    assert sources == {"pcap", "pdf"}
    times = [event["canoe_time_s"] for event in document["timeline"]]
    assert times == sorted(times)
    assert any(e["wall_clock"] == "12:24:05.100" and "gestört" in e["event"] for e in document["timeline"])


def test_report_only_analysis(synthetic_report):
    document = analyze(None, synthetic_report)
    AnalysisScenarios.model_validate(document)
    assert document["gfma_state_history"]["states"] == []
    tc2 = document["test_cases"][1]
    # without a capture the state comes from the report text
    assert "(the GFM-A reported 'gestört, nicht grundst.')" in tc2["root_cause"]
    assert {s["title"].split(":")[0] for s in document["scenarios"]} >= {"Preparation timed out"}


def test_communication_problems_are_reported():
    builder = CaptureBuilder()
    builder.session(0.0, 5.0, [], disconnect_reason=4)
    builder.packets.append((5.05, icmp_port_unreachable(OC_IP, ZE_IP)))
    builder.packets = [p for p in builder.packets if not 2.0 < p[0] < 3.2]  # 1.2 s without any PDU
    document = analyze(("trace.pcapng", builder.build()), None)
    problems = _finding(document, "Communication problems")
    assert problems["severity"] == "High"
    evidence = " | ".join(problems["evidence"])
    assert "disconnected with reason 'Timeout'" in evidence
    assert "more than 750 ms" in evidence
    assert "sequence gap" in evidence
    assert "1 ICMP 'port unreachable'" in evidence


def test_command_answered_late_is_reported():
    builder = CaptureBuilder()
    builder.session(0.0, 20.0, [
        (2.0, "oc", [gfma_state(BELEGT, 0, 0x0001)]),
        (2.1, "ze", [sci(0x0003, "DETHMM ZE 35##0001", SECTION)]),
        (13.3, "oc", [gfma_state(BELEGT, 1, 0x0001)]),
    ])
    document = analyze(("trace.pcapng", builder.build()), None)
    slow = _finding(document, "Slow OC reaction")
    assert "answered after 11.2 s" in slow["title"]


@pytest.mark.skipif(not (REAL_CAPTURE.exists() and REAL_REPORT.exists()), reason="test-bench files not available")
def test_real_test_bench_files():
    document = analyze((REAL_CAPTURE.name, REAL_CAPTURE.read_bytes()), (REAL_REPORT.name, REAL_REPORT.read_bytes()))
    AnalysisScenarios.model_validate(document)
    verdicts = [tc["verdict"] for tc in document["test_cases"]]
    assert verdicts == ["Pass", "Pass", "Fail", "Fail", "Inconclusive"]
    tc3, tc4, tc5 = document["test_cases"][2:]
    assert "102 ms after an occupation with an invalid axle count (0x0000)" in tc3["root_cause"]
    assert tc4["root_cause"].startswith("Follow-up failure: TC3 left the GFM-A 'gestört, nicht grundst.'")
    assert "stopped the test unit manually" in tc5["root_cause"]
    assert _finding(document, "Communication layer ruled out")["severity"] == "Info"
    assert _finding(document, "not sent by the test script")["test_cases"] == ["TC_NPRO.295.00525.01"]
