"""
Rule-based analysis of an uploaded SCI-TDS capture (pcapng/pcap) and/or CANoe test report (PDF).

The result uses the analysis-scenarios format (src/models/scenarios.py), so the Web GUI shows an
uploaded analysis with the same summary, findings, test-case, timeline and GFM-A views as the
data-analysis workbook.
"""
import re
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.analyzer.capture import CaptureFormatError, decode_icmp_unreachable, decode_udp, read_packets
from src.analyzer.report import ReportFailure, ReportTestCase, TestReport, read_report
from src.analyzer.traffic import build_io_graph
from src.analyzer.sci import (
    AUFRUEST_TYPES,
    CONNECTION_REQUEST,
    CONNECTION_RESPONSE,
    DATA,
    DISCONNECT_REASONS,
    DISCONNECT_REQUEST,
    KOMMANDO_AZG,
    KOMMANDO_AZGH,
    MELDUNG_AZGH_QUITTUNG,
    MELDUNG_BELEGUNGSZUSTAND,
    MELDUNG_KOMMANDO_ABGEWIESEN,
    MELDUNG_VERSION,
    OCCUPANCY,
    RESETTABLE,
    RETRANSMISSION_TYPES,
    RastaPdu,
    SciTelegram,
    decode_rasta,
    decode_sci,
)

MAX_LINK_GAP_S = 0.75  # largest RaSTA message gap that still counts as a healthy link
REACTION_LIMIT_S = 0.5  # "t - t1 < 500 ms" used by the SCI-TDS test specification
REACTION_SEARCH_S = 30.0  # how long to look for the OC's reaction to a command
TRIGGER_LOOKBACK_S = 2.0  # an occupation report this close before 'gestört' is treated as its trigger
COMMAND_MATCH_S = 0.25  # a command in the capture this close to a "Sende '...'" report line was sent by the script
OFFSET_MAX_SPREAD_S = 0.005
MAX_TIMELINE_EVENTS = 400
MAX_STATE_EVENTS = 1000
MAX_EVIDENCE_LINES = 12
MAX_EPISODE_FINDINGS = 3  # 'gestört' episodes per section reported as separate findings
SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
FREI, BELEGT, GESTOERT = 1, 2, 3


# ---------------------------------------------------------------------------
# Decoded data
# ---------------------------------------------------------------------------

@dataclass
class Frame:
    number: int
    time_s: float
    wall: datetime
    src: str
    dst: str
    pdu: RastaPdu
    telegrams: List[SciTelegram]


@dataclass
class StateReport:
    frame: int
    index: int
    time_s: float
    section: str
    occupancy: int
    resettable: int
    axle_count: int
    initial: bool  # reported during Aufrüstung (start of a RaSTA session)

    @property
    def label(self) -> str:
        return f"{OCCUPANCY.get(self.occupancy, 'ungültig')}, {RESETTABLE.get(self.resettable, 'ungültig')}"

    @property
    def where(self) -> str:
        return f"{self.time_s:.3f} s (frame {self.frame})"


@dataclass
class Command:
    frame: int
    time_s: float
    name: str
    detail: Optional[str]
    target: str
    state_before: Optional[StateReport]
    reaction: Optional[StateReport] = None
    rejected: Optional[str] = None
    acknowledged: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} [{self.detail}]" if self.detail else self.name

    @property
    def answered(self) -> bool:
        return self.reaction is not None or self.rejected is not None or self.acknowledged


@dataclass
class Session:
    number: int
    start_s: float
    end_s: float
    version: Optional[str] = None
    answered: bool = False
    disconnect_reason: Optional[int] = None


@dataclass
class CaptureData:
    file_name: str
    frame_count: int
    duration_s: float
    first_wall: datetime
    offset_s: Optional[float]
    offset_spread_ms: Optional[float]
    ze_ip: Optional[str] = None
    oc_ip: Optional[str] = None
    ze_id: Optional[str] = None
    oc_id: Optional[str] = None
    port: Optional[int] = None
    frames: List[Frame] = field(default_factory=list)
    icmp: List[Tuple[int, float, str, str]] = field(default_factory=list)
    sessions: List[Session] = field(default_factory=list)
    states: List[StateReport] = field(default_factory=list)
    commands: List[Command] = field(default_factory=list)
    rejections: List[Tuple[int, float, str]] = field(default_factory=list)
    version_results: List[Tuple[int, float, int]] = field(default_factory=list)
    io_graph: Optional[dict] = None
    max_gap_s: Dict[str, float] = field(default_factory=dict)
    sequence_problems: List[str] = field(default_factory=list)
    retransmissions: int = 0
    heartbeat_interval_ms: Optional[float] = None

    @property
    def end_s(self) -> float:
        return self.frames[-1].time_s if self.frames else 0.0

    def direction(self, src: str) -> str:
        if src == self.ze_ip:
            return "ZE -> OC"
        if src == self.oc_ip:
            return "OC -> ZE"
        return f"{src} ->"

    def state_before(self, section: str, time_s: float) -> Optional[StateReport]:
        earlier = [s for s in self.states if s.section == section and s.time_s < time_s]
        return earlier[-1] if earlier else None

    def main_section(self) -> Optional[str]:
        counts: Dict[str, int] = {}
        for state in self.states:
            counts[state.section] = counts.get(state.section, 0) + 1
        return max(counts, key=lambda section: counts[section]) if counts else None


@dataclass
class Finding:
    title: str
    category: str
    severity: str
    confidence: str
    symptom: str
    evidence: List[str]
    root_cause: str
    recommendation: str
    method: str
    sources: List[str]
    potential_reasons: List[str] = field(default_factory=list)
    times: List[float] = field(default_factory=list)
    frame_notes: Dict[int, str] = field(default_factory=dict)
    report_notes: Dict[float, str] = field(default_factory=dict)
    applies_to_all: bool = False
    kind: str = ""  # rule that produced the finding, used to explain the test cases in plain language
    facts: Dict[str, object] = field(default_factory=dict)
    id: str = ""
    test_cases: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capture decoding
# ---------------------------------------------------------------------------

def decode_capture(file_name: str, data: bytes, tz: Optional[timezone]) -> CaptureData:
    packets = [p for p in read_packets(data) if p.timestamp > 0]
    if not packets:
        raise CaptureFormatError("The capture contains no timestamped packets.")
    start = packets[0].timestamp

    def wall(timestamp: float) -> datetime:
        moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return moment.astimezone(tz) if tz else moment.astimezone()

    raw_frames: List[Tuple[object, object, RastaPdu, float]] = []
    icmp = []
    for packet in packets:
        udp = decode_udp(packet)
        pdu = decode_rasta(udp.payload) if udp else None
        if pdu is not None:
            raw_frames.append((packet, udp, pdu, packet.timestamp - start))
            continue
        unreachable = decode_icmp_unreachable(packet)
        if unreachable is not None:
            icmp.append((packet.number, packet.timestamp - start, unreachable.src, unreachable.dst))

    ze_ip = next((udp.src for _, udp, pdu, _ in raw_frames if pdu.pdu_type == CONNECTION_REQUEST), None)
    if ze_ip is None:
        ze_ip = next((udp.src for _, udp, pdu, _ in raw_frames
                      for m in pdu.messages if (t := decode_sci(m)) and t.is_command), None)
    oc_ip = next((udp.dst for _, udp, _, _ in raw_frames if udp.src == ze_ip), None) if ze_ip else None

    # CANoe stamps the RaSTA timestamp of the PDUs it sends with its measurement time (µs or ms):
    # the median difference to the capture time aligns the capture with the test report.
    offset, spread = None, None
    for divisor in (1e6, 1e3):
        candidates = [pdu.timestamp / divisor - rel for _, udp, pdu, rel in raw_frames if udp.src == ze_ip]
        if len(candidates) >= 3:
            median = statistics.median(candidates)
            deviation = statistics.median(abs(c - median) for c in candidates)
            if deviation <= OFFSET_MAX_SPREAD_S and median > -1:
                offset, spread = median, deviation * 1000
                break

    shift = offset or 0.0
    capture = CaptureData(
        file_name=file_name,
        frame_count=packets[-1].number,
        duration_s=packets[-1].timestamp - start,
        first_wall=wall(start),
        offset_s=offset,
        offset_spread_ms=spread,
        ze_ip=ze_ip,
        oc_ip=oc_ip,
        icmp=[(number, rel + shift, src, dst) for number, rel, src, dst in icmp],
    )
    for packet, udp, pdu, rel in raw_frames:
        telegrams = [t for t in (decode_sci(m) for m in pdu.messages) if t is not None]
        capture.frames.append(Frame(packet.number, rel + shift, wall(packet.timestamp), udp.src, udp.dst, pdu, telegrams))
        capture.port = capture.port or udp.dst_port

    roles = {ip: role for ip, role in ((ze_ip, "ESTW-ZE (CANoe)"), (oc_ip, "Object controller")) if ip}
    capture.io_graph = build_io_graph(
        file_name, packets, roles,
        canoe_zero_epoch_s=start - offset if offset is not None else None,
        utc_offset_min=int(tz.utcoffset(None).total_seconds() // 60) if tz else None,
    )
    _decode_sessions(capture)
    _decode_telegrams(capture)
    return capture


def _decode_sessions(capture: CaptureData) -> None:
    session: Optional[Session] = None
    closed = False
    last_seq: Dict[str, int] = {}
    last_time: Dict[str, float] = {}
    heartbeat_gaps: List[float] = []
    for frame in capture.frames:
        pdu = frame.pdu
        direction = capture.direction(frame.src)
        if pdu.pdu_type == CONNECTION_REQUEST:
            session = Session(len(capture.sessions) + 1, frame.time_s, frame.time_s, version=pdu.version)
            capture.sessions.append(session)
            closed = False
            last_seq, last_time = {}, {}
        elif session is None:
            # the capture started inside an already established session
            session = Session(1, frame.time_s, frame.time_s, answered=True)
            capture.sessions.append(session)
        elif closed:
            continue  # heartbeat that was still in flight when the peer disconnected
        session.end_s = frame.time_s
        if pdu.pdu_type == CONNECTION_RESPONSE:
            session.answered = True
            session.version = session.version or pdu.version
        if pdu.pdu_type == DISCONNECT_REQUEST:
            session.disconnect_reason = pdu.disconnect_reason
        if pdu.pdu_type in RETRANSMISSION_TYPES:
            capture.retransmissions += 1

        if direction in last_seq:
            expected = (last_seq[direction] + 1) & 0xFFFFFFFF
            if pdu.seq == last_seq[direction]:
                capture.sequence_problems.append(f"repeated sequence number {pdu.seq} ({direction}, frame {frame.number})")
            elif pdu.seq != expected and pdu.pdu_type not in RETRANSMISSION_TYPES:
                capture.sequence_problems.append(
                    f"sequence gap {last_seq[direction]} -> {pdu.seq} ({direction}, frame {frame.number})"
                )
            gap = frame.time_s - last_time[direction]
            capture.max_gap_s[direction] = max(capture.max_gap_s.get(direction, 0.0), gap)
            heartbeat_gaps.append(gap)
        last_seq[direction] = pdu.seq
        last_time[direction] = frame.time_s
        if pdu.pdu_type == DISCONNECT_REQUEST:
            closed = True
    if heartbeat_gaps:
        capture.heartbeat_interval_ms = statistics.median(heartbeat_gaps) * 1000


def _decode_telegrams(capture: CaptureData) -> None:
    for frame in capture.frames:
        initial = any(t.message_type in AUFRUEST_TYPES for t in frame.telegrams)
        for index, telegram in enumerate(frame.telegrams, 1):
            if telegram.message_type == MELDUNG_VERSION:
                capture.version_results.append((frame.number, frame.time_s, int(telegram.fields.get("ergebnis", 0))))
                capture.oc_id = capture.oc_id or telegram.sender
                capture.ze_id = capture.ze_id or telegram.receiver
            if telegram.protocol != "TDS":
                continue
            if telegram.message_type == MELDUNG_BELEGUNGSZUSTAND:
                capture.states.append(StateReport(
                    frame.number, index, frame.time_s, telegram.sender,
                    int(telegram.fields["belegung"]), int(telegram.fields["grundstellbar"]),
                    int(telegram.fields["achszaehlfuellstand"]), initial,
                ))
            elif telegram.message_type in (KOMMANDO_AZG, KOMMANDO_AZGH):
                capture.commands.append(Command(
                    frame.number, frame.time_s, "AZG" if telegram.message_type == KOMMANDO_AZG else "AZGH",
                    str(telegram.fields.get("grundstellungsart_text")) if telegram.message_type == KOMMANDO_AZG else None,
                    telegram.receiver, None,
                ))
            elif telegram.message_type == MELDUNG_KOMMANDO_ABGEWIESEN:
                capture.rejections.append((frame.number, frame.time_s, str(telegram.fields.get("abweisungsgrund_text"))))

    states: Dict[str, List[StateReport]] = {}
    for state in capture.states:
        states.setdefault(state.section, []).append(state)
    state_times = {section: [s.time_s for s in reports] for section, reports in states.items()}
    rejection_times = [time_s for _, time_s, _ in capture.rejections]
    acknowledgements = [frame.time_s for frame in capture.frames for t in frame.telegrams
                        if t.protocol == "TDS" and t.message_type == MELDUNG_AZGH_QUITTUNG]

    for position, command in enumerate(capture.commands):
        reports, times = states.get(command.target, []), state_times.get(command.target, [])
        before = bisect_left(times, command.time_s)
        command.state_before = reports[before - 1] if before else None
        next_command = capture.commands[position + 1].time_s if position + 1 < len(capture.commands) else float("inf")
        session_end = next((s.end_s for s in capture.sessions if s.start_s <= command.time_s <= s.end_s), capture.end_s)
        horizon = min(next_command, session_end, command.time_s + REACTION_SEARCH_S)
        after = bisect_right(times, command.time_s)
        command.reaction = reports[after] if after < len(reports) and times[after] <= horizon else None
        rejection = bisect_right(rejection_times, command.time_s)
        if rejection < len(rejection_times) and rejection_times[rejection] <= horizon:
            command.rejected = capture.rejections[rejection][2]
        acknowledgement = bisect_right(acknowledgements, command.time_s)
        command.acknowledged = acknowledgement < len(acknowledgements) and acknowledgements[acknowledgement] <= horizon


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def _secs(seconds: float) -> str:
    return f"{seconds:.1f} s"


def rule_communication(capture: CaptureData) -> Finding:
    problems: List[str] = []
    unanswered = [s for s in capture.sessions if not s.answered]
    if unanswered:
        problems.append(f"{len(unanswered)} connection request(s) not answered (session {', '.join(str(s.number) for s in unanswered)})")
    abnormal = [s for s in capture.sessions if s.disconnect_reason not in (None, 0)]
    for session in abnormal:
        problems.append(
            f"session {session.number} disconnected with reason '{DISCONNECT_REASONS.get(session.disconnect_reason, session.disconnect_reason)}'"
        )
    failed_checks = [result for result in capture.version_results if result[2] != 2]
    for frame, time_s, _ in failed_checks:
        problems.append(f"BTP version check failed at {time_s:.3f} s (frame {frame}): 'BTP-Versionswerte nicht gleich'")
    if capture.retransmissions:
        problems.append(f"{capture.retransmissions} RaSTA retransmission PDU(s)")
    problems.extend(capture.sequence_problems[:5])
    slow = {direction: gap for direction, gap in capture.max_gap_s.items() if gap > MAX_LINK_GAP_S}
    for direction, gap in slow.items():
        problems.append(f"message gap of {_ms(gap)} ({direction}), more than {_ms(MAX_LINK_GAP_S)}")

    gaps = ", ".join(f"{direction} max {_ms(gap)}" for direction, gap in sorted(capture.max_gap_s.items()))
    evidence = [
        f"{len(capture.sessions)} RaSTA session(s) between {capture.ze_ip} (ESTW-ZE) and {capture.oc_ip} (OC), "
        f"protocol version {', '.join(sorted({s.version for s in capture.sessions if s.version})) or 'unknown'}",
        f"BTP version check: {len(capture.version_results) - len(failed_checks)} of {len(capture.version_results)} "
        "'BTP-Versionswerte gleich'",
    ]
    if capture.heartbeat_interval_ms:
        evidence.append(f"Heartbeat interval ~{capture.heartbeat_interval_ms:.0f} ms; message gaps: {gaps}")
    if capture.icmp:
        evidence.append(
            f"{len(capture.icmp)} ICMP 'port unreachable' (frames {', '.join(str(i[0]) for i in capture.icmp)}) "
            "right after disconnects: a heartbeat still in flight, benign"
        )

    if not problems:
        evidence.append("No sequence-number gaps or repeats, no retransmissions; all disconnects 'User Request'")
        return Finding(
            title="Communication layer ruled out: RaSTA/BTP link healthy",
            category="Network / protocol (negative finding)",
            severity="Info",
            confidence="High",
            symptom="The RaSTA/BTP link worked without errors for the whole capture.",
            evidence=evidence,
            root_cause="No telegram loss, timeout or connection interruption was found, so the network and the "
                       "RaSTA/BTP connection are not the cause of failing test steps.",
            recommendation="No action needed on the network.",
            method="Checked every RaSTA PDU: session setup, version check, heartbeat gaps per direction, sequence "
                   "numbers, retransmissions and disconnect reasons.",
            sources=["pcap"],
            applies_to_all=True,
            frame_notes={number: "benign, heartbeat after disconnect" for number, _, _, _ in capture.icmp},
            kind="communication",
        )
    return Finding(
        title="Communication problems on the SCI-TDS link",
        category="Network / protocol",
        severity="High",
        confidence="High",
        symptom="The RaSTA/BTP connection between ESTW-ZE and object controller was disturbed.",
        evidence=problems + evidence,
        root_cause="Telegrams may have been lost, delayed or rejected on the communication layer, so test steps "
                   "can fail although the object controller behaves correctly.",
        potential_reasons=["Network latency or packet loss (switch, gateway, VLAN)", "RaSTA timer parameters (Tmax, Th) "
                           "not matching the setup", "Device or test PC overload", "Protocol version mismatch"],
        recommendation="Check the network path and RaSTA timer configuration, then repeat the affected test cases.",
        method="Checked every RaSTA PDU: session setup, version check, heartbeat gaps per direction, sequence "
               "numbers, retransmissions and disconnect reasons.",
        sources=["pcap"],
        applies_to_all=True,
        kind="communication_problem",
    )


def rule_disturbances(capture: CaptureData, report_failure_times: List[float]) -> List[Finding]:
    findings = []
    for section in sorted({s.section for s in capture.states}):
        states = [s for s in capture.states if s.section == section]
        episodes = 0
        further: List[StateReport] = []
        index = 0
        while index < len(states):
            state = states[index]
            previous = states[index - 1] if index else None
            if state.occupancy != GESTOERT or (previous and previous.occupancy == GESTOERT) or state.initial:
                index += 1
                continue
            episode = [state]
            while index + 1 < len(states) and states[index + 1].occupancy == GESTOERT:
                index += 1
                episode.append(states[index])
            recovered = states[index + 1] if index + 1 < len(states) else None
            end_s = recovered.time_s if recovered else capture.end_s
            index += 1
            episodes += 1
            if episodes > MAX_EPISODE_FINDINGS:
                further.append(state)
                continue

            evidence, notes = [], {state.frame: "became gestört (disturbed)"}
            trigger = previous if previous and state.time_s - previous.time_s <= TRIGGER_LOOKBACK_S else None
            invalid_trigger = trigger is not None and trigger.occupancy == BELEGT and trigger.axle_count == 0
            delay_s = state.time_s - trigger.time_s if trigger else None
            if trigger:
                evidence.append(f"{trigger.where}: {trigger.label}, axle count 0x{trigger.axle_count:04X}"
                                + (" (INVALID)" if invalid_trigger else ""))
                notes[trigger.frame] = "occupation with axle count 0x0000 (invalid)" if invalid_trigger else "state before disturbance"
            evidence.append(f"{state.where}: {state.label}, axle count 0x{state.axle_count:04X}"
                            + (f" ({_ms(delay_s)} later)" if trigger else ""))
            evidence.append(
                f"Stayed gestört for {_secs(end_s - state.time_s)}"
                + (f" until {recovered.where} ({recovered.label})" if recovered else " until the end of the capture")
            )
            failures_during = [t for t in report_failure_times if state.time_s <= t <= end_s + 1]
            title = f"GFM-A {section} became 'gestört'"
            title += f" {_ms(delay_s)} after an occupation without a valid axle count" if invalid_trigger else ""
            findings.append(Finding(
                title=title,
                category="SUT state / physical stimulation",
                severity="High" if failures_during or end_s - state.time_s > 60 else "Medium",
                confidence="High",
                symptom=f"The GFM-A reported Belegungszustand 3 (gestört) at {state.time_s:.3f} s"
                        + (" and never recovered in this capture." if not recovered else f" for {_secs(end_s - state.time_s)}."),
                evidence=evidence,
                root_cause=("The occupation was not counted as a valid axle (fill level 0x0000), so the axle counter "
                            "judged the wheel-sensor signal as implausible and declared the section disturbed. "
                            if invalid_trigger else "The axle counter declared the section disturbed. ")
                + "A disturbed section only returns to a defined state after AZG/AZGH while it is 'grundstellbar'; "
                  "until then every preparation that needs 'frei' or 'belegt' times out.",
                potential_reasons=[
                    "Metal object placed on/removed from only one sensor system or in the wrong order",
                    "Object moved too fast or too slow, partial influence of the sensor",
                    "Wheel sensor fault, adjustment or EMI",
                    "Manual stimulation not reproducible",
                ],
                recommendation="Use a defined, documented stimulation procedure (or a wheel-sensor simulator) and let "
                               "the test fail fast when Belegungszustand 3 is reported during preparation.",
                method=f"Followed every 'Meldung GFM-A Belegungszustand' (0x0007) of {section} and inspected the "
                       "report before the change to 'gestört'.",
                sources=["pcap"],
                times=[state.time_s] + failures_during,
                frame_notes=notes,
                kind="disturbance",
                facts={"section": section, "start_s": state.time_s, "end_s": end_s, "delay_s": delay_s,
                       "invalid": invalid_trigger},
            ))
        if further:
            findings.append(Finding(
                title=f"GFM-A {section} became 'gestört' {len(further)} more time(s)",
                category="SUT state / physical stimulation",
                severity="Medium",
                confidence="High",
                symptom=f"Belegungszustand 3 (gestört) was reported in {episodes} separate episodes.",
                evidence=[f"{s.where}: {s.label}, axle count 0x{s.axle_count:04X}" for s in further],
                root_cause="The section was disturbed repeatedly; each episode blocks the tests until AZG/AZGH restores it.",
                recommendation="Check the wheel sensors and the stimulation procedure before repeating the tests.",
                method=f"Followed every 'Meldung GFM-A Belegungszustand' (0x0007) of {section}.",
                sources=["pcap"],
                times=[s.time_s for s in further],
                frame_notes={s.frame: "became gestört (disturbed)" for s in further},
                kind="disturbances_more",
            ))
    return findings


def rule_inherited_state(capture: CaptureData, report: Optional[TestReport]) -> List[Finding]:
    cases = []
    for session in capture.sessions[1:]:
        initial = next((s for s in capture.states if s.initial and session.start_s <= s.time_s <= session.end_s), None)
        if initial is None or initial.occupancy != GESTOERT:
            continue
        test_case = report.test_case_at(initial.time_s) if report and capture.offset_s is not None else None
        position = report.test_cases.index(test_case) if test_case else 0
        previous = report.test_cases[position - 1] if test_case and position else None
        cleanup_failures = [f for f in previous.failures if "cleanup" in f.text.lower()] if previous else []
        later = [s for s in capture.states if session.start_s <= s.time_s <= session.end_s and s.frame != initial.frame]
        cases.append((session, initial, test_case, previous, cleanup_failures,
                      not any(s.occupancy != GESTOERT for s in later)))
    if not cases:
        return []

    evidence, report_notes = [], {}
    for session, initial, test_case, previous, cleanup_failures, unchanged in cases:
        for failure in cleanup_failures[:1]:
            evidence.append(f"{failure.canoe_time_s:.3f} s: {previous.label} cleanup failed: {failure.text}")
            report_notes[failure.canoe_time_s] = "cleanup failed - no defined start state"
        evidence.append(f"{initial.where}: {test_case.label if test_case else f'RaSTA session {session.number}'} "
                        f"started with '{initial.label}' (state reported at Aufrüstung)")
        if unchanged:
            evidence.append(f"No state change until the session ended at {session.end_s:.3f} s")

    _, _, test_case, previous, _, _ = cases[0]
    if len(cases) == 1:
        name = f"TC{test_case.number}" if test_case else f"RaSTA session {cases[0][0].number}"
        title = f"Cascading failure: {name} started in the disturbed state " + (
            f"left by TC{previous.number}" if previous else "left over from the previous session")
    else:
        names = ", ".join(f"TC{c[2].number}" if c[2] else f"session {c[0].number}" for c in cases)
        title = f"Cascading failures: {names} started in the disturbed state left by the previous test"
    failed = [c for c in cases if c[2] is None or c[2].verdict != "Pass"]
    return [Finding(
        title=title,
        category="Test isolation / sequencing",
        severity="High" if failed else "Medium",
        confidence="High",
        symptom="A test began while the GFM-A was already 'gestört'.",
        evidence=evidence,
        root_cause="The test continued although the previous test case did not restore a defined state. A disturbed "
                   "GFM-A cannot be cleared by driving through it; it needs 'grundstellbar' plus AZG/AZGH.",
        potential_reasons=["No gate between test cases (continue despite failed cleanup)",
                           "No automatic recovery procedure", "Operator instruction does not fit state 'gestört'"],
        recommendation="Make a successful cleanup a precondition for the next test case (skip/block with a reason) "
                       "and add a recovery routine for 'gestört'.",
        method="Compared the state reported at the start of each RaSTA session (Aufrüstung) with the previous test case.",
        sources=["pcap", "pdf"] if report_notes else ["pcap"],
        times=[c[1].time_s for c in cases],
        frame_notes={c[1].frame: "starts in disturbed state" for c in cases},
        report_notes=report_notes,
        kind="inherited",
        facts={"cases": [{"test_case_id": c[2].test_case_id if c[2] else None,
                          "previous": f"TC{c[3].number}" if c[3] else None,
                          "state": c[1].label, "cleanup_failed": bool(c[4])} for c in cases]},
    )]


def _automatic_resettable(capture: CaptureData) -> List[Tuple[StateReport, StateReport]]:
    """State changes to 'grundstellbar' that happened without any AZG/AZGH since the previous report."""
    result = []
    for section in sorted({s.section for s in capture.states}):
        states = [s for s in capture.states if s.section == section]
        for previous, state in zip(states, states[1:]):
            if previous.resettable == 0 and state.resettable == 1 and not state.initial and not any(
                    c.target == section and previous.time_s < c.time_s <= state.time_s for c in capture.commands):
                result.append((previous, state))
    return result


def rule_commands(capture: CaptureData) -> List[Finding]:
    findings = []
    slow = [c for c in capture.commands if c.reaction and c.reaction.time_s - c.time_s > REACTION_LIMIT_S]
    if slow:
        worst = max(slow, key=lambda c: c.reaction.time_s - c.time_s)
        delay = worst.reaction.time_s - worst.time_s
        evidence = [
            f"{c.label} at {c.time_s:.3f} s (frame {c.frame}) in state '{c.state_before.label if c.state_before else 'unknown'}' "
            f"-> {c.reaction.label} at {c.reaction.where}: {_secs(c.reaction.time_s - c.time_s)}"
            for c in slow
        ]
        root_cause = (f"The GFM-A report followed {_secs(delay)} after the command, about {delay / REACTION_LIMIT_S:.0f}x the "
                      f"{_ms(REACTION_LIMIT_S)} a test step allows. A step that expects the reaction within "
                      f"{_ms(REACTION_LIMIT_S)} fails even when the OC works as designed.")
        automatic = _automatic_resettable(capture)
        notes = {**{c.frame: f"{c.label} sent" for c in slow},
                 **{c.reaction.frame: f"{_secs(c.reaction.time_s - c.time_s)} after {c.label}" for c in slow}}
        for previous, state in automatic[:2]:
            evidence.append(f"Without any command the GFM-A also became '{state.label}' {_secs(state.time_s - previous.time_s)} "
                            f"after '{previous.label}' ({state.time_s:.3f} s, frame {state.frame})")
            notes.setdefault(state.frame, f"grundstellbar {_secs(state.time_s - previous.time_s)} after the last change, no command")
        if automatic:
            root_cause += (" The OC also set 'grundstellbar' without any command after a similar time, so the change "
                           "probably follows a fixed OC delay rather than the command.")
        findings.append(Finding(
            title=f"Slow OC reaction: {worst.label} answered after {_secs(delay)}, test window is {_ms(REACTION_LIMIT_S)}",
            category="Timing / requirement",
            severity="Medium",
            confidence="Medium",
            symptom=f"{len(slow)} command(s) were answered later than the {_ms(REACTION_LIMIT_S)} window of the test specification.",
            evidence=evidence,
            root_cause=root_cause,
            potential_reasons=["OC sets 'grundstellbar' after a fixed internal delay",
                               "Timing value derived for a simulated OC", "Different baseline between test spec and OC"],
            recommendation="Clarify the reaction-time requirement with the OC supplier and parameterise the test window.",
            method="Measured the time from each AZG/AZGH to the next GFM-A report of the addressed section.",
            sources=["pcap"],
            times=[c.time_s for c in slow],
            frame_notes=notes,
            kind="slow_reaction",
        ))

    silent = [c for c in capture.commands if not c.answered]
    if silent and not capture.rejections:
        findings.append(Finding(
            title=f"{len(silent)} AZG/AZGH command(s) discarded silently: no 'Meldung Kommando abgewiesen' (0x0006)",
            category="Protocol / specification ambiguity",
            severity="Medium",
            confidence="High",
            symptom="Commands without any reaction from the OC; message type 0x0006 never appears in the capture.",
            evidence=[f"{c.label} at {c.time_s:.3f} s (frame {c.frame}) in state "
                      f"'{c.state_before.label if c.state_before else 'unknown'}': no reaction" for c in silent],
            root_cause="Without a negative acknowledgement the ESTW-ZE cannot distinguish a discarded command from a "
                       "lost one, and tests that only check 'no reaction within 500 ms' cannot tell why.",
            potential_reasons=["Rejection only sent for specific reasons in this baseline",
                               "OC configuration/software differs from the use-case documentation"],
            recommendation="Clarify with the requirement owner whether 0x0006 is required and add an explicit "
                           "expectation (present or absent) to the test cases.",
            method="Checked every AZG/AZGH for a GFM-A report, rejection (0x0006) or AZGH acknowledgement until the "
                   "next command or the end of the session.",
            sources=["pcap"],
            times=[c.time_s for c in silent],
            frame_notes={c.frame: f"{c.label} - no reaction" for c in silent},
            kind="silent_discard",
        ))

    futile = [c for c in silent if c.state_before and c.state_before.occupancy == GESTOERT and c.state_before.resettable == 0]
    if futile:
        findings.append(Finding(
            title=f"{len(futile)} recovery command(s) sent while GFM-A was 'gestört' and not 'grundstellbar'",
            category="Test script logic / operation",
            severity="Medium",
            confidence="High",
            symptom="AZG/AZGH were sent to a disturbed section that did not report 'grundstellbar'; all were discarded.",
            evidence=[f"{c.label} at {c.time_s:.3f} s (frame {c.frame}) in state '{c.state_before.label}'" for c in futile],
            root_cause="The OC discards AZG/AZGH while the section is not 'grundstellbar', so these recovery attempts "
                       "(cleanup or manual panel actions) could not succeed.",
            potential_reasons=["Cleanup not state-aware (always one AZGH, fixed timeout)",
                               "Operator unaware that commands are rejected in this state"],
            recommendation="Implement a state-aware recovery: wait for 'grundstellbar', then send AZG/AZGH and verify "
                           "'frei'; otherwise stop with 'manual intervention needed'.",
            method="Compared the GFM-A state at the time of every unanswered command.",
            sources=["pcap"],
            times=[c.time_s for c in futile],
            frame_notes={c.frame: f"{c.label} while not grundstellbar" for c in futile},
            kind="futile_commands",
        ))

    if capture.rejections:
        findings.append(Finding(
            title=f"OC rejected {len(capture.rejections)} command(s) ('Meldung Kommando abgewiesen')",
            category="Protocol",
            severity="Low",
            confidence="High",
            symptom="The OC answered commands with message type 0x0006.",
            evidence=[f"{time_s:.3f} s (frame {frame}): rejected ({reason})" for frame, time_s, reason in capture.rejections],
            root_cause="The OC refused commands for operational or technical reasons; check whether the test expected it.",
            recommendation="Compare the rejections with the expected result of the affected test steps.",
            method="Collected all 'Meldung Kommando abgewiesen' (0x0006) telegrams.",
            sources=["pcap"],
            times=[time_s for _, time_s, _ in capture.rejections],
            frame_notes={frame: "command rejected" for frame, _, _ in capture.rejections},
            kind="rejections",
        ))
    return findings


def rule_unused_window(capture: CaptureData) -> List[Finding]:
    findings = []
    for section in sorted({s.section for s in capture.states}):
        states = [s for s in capture.states if s.section == section]
        for position, state in enumerate(states):
            if state.occupancy != GESTOERT or state.resettable != 1:
                continue
            if position and states[position - 1].occupancy == GESTOERT and states[position - 1].resettable == 1:
                continue
            end = next((s for s in states[position + 1:] if not (s.occupancy == GESTOERT and s.resettable == 1)), None)
            end_s = end.time_s if end else capture.end_s
            commands = [c for c in capture.commands if c.target == section and state.time_s <= c.time_s <= end_s]
            if commands:
                continue
            previous = states[position - 1] if position else None
            evidence = []
            notes = {state.frame: "grundstellbar without any command" if previous else "grundstellbar"}
            if previous and previous.occupancy == GESTOERT:
                evidence.append(f"{previous.where}: {previous.label} -> {state.where}: {state.label} "
                                f"after {_secs(state.time_s - previous.time_s)} without any command")
            evidence.append(f"Window {state.time_s:.3f} s - {end_s:.3f} s ({_secs(end_s - state.time_s)}): no AZG/AZGH sent")
            if end:
                evidence.append(f"{end.where}: {end.label} (Grundstellbarkeit withdrawn)")
                notes[end.frame] = "grundstellbarkeit withdrawn"
            findings.append(Finding(
                title=f"Missed recovery window: GFM-A {section} was 'grundstellbar' for {_secs(end_s - state.time_s)} and no AZG/AZGH was sent",
                category="Test script logic / SUT behaviour",
                severity="Medium",
                confidence="Medium",
                symptom="Not visible in the test report - only in the trace.",
                evidence=evidence,
                root_cause="An AZG/AZGH in this window would have restored a defined state. Afterwards the OC withdrew "
                           "'grundstellbar' and every later recovery attempt was discarded.",
                potential_reasons=["The preparation step forbids panel commands", "OC time limit for Grundstellbarkeit"],
                recommendation="React to 'grundstellbar' while the section is disturbed: send AZG automatically or "
                               "prompt the operator, and log the event in the report.",
                method="Listed all GFM-A state changes with their durations and checked for commands inside each "
                       "'gestört, grundstellbar' window.",
                sources=["pcap"],
                times=[state.time_s],
                frame_notes=notes,
                kind="missed_window",
                facts={"section": section, "start_s": state.time_s, "end_s": end_s},
            ))
    return findings


def rule_unlogged_commands(capture: CaptureData, report: TestReport) -> List[Finding]:
    """Commands in the capture that the test script did not send (no "Sende '...'" line in the report)."""
    if not report.sent_commands:
        return []  # this report does not log the telegrams it sends, so the check is not possible
    unlogged = []
    for command in capture.commands:
        test_case = report.test_case_at(command.time_s)
        if test_case and not any(abs(time_s - command.time_s) <= COMMAND_MATCH_S for time_s, _ in report.sent_commands):
            unlogged.append((command, test_case))
    if not unlogged:
        return []

    names = ", ".join(dict.fromkeys(f"TC{tc.number}" for _, tc in unlogged))
    evidence = []
    for command, test_case in unlogged:
        result = "no reaction" if not command.answered else (
            f"answered: {command.reaction.label}" if command.reaction else "acknowledged/rejected")
        evidence.append(f"{command.label} at {command.time_s:.3f} s (frame {command.frame}) during {test_case.label}, "
                        f"state '{command.state_before.label if command.state_before else 'unknown'}': {result}")
    evidence.append(f"The report logs {len(report.sent_commands)} telegrams sent by the test script; none within "
                    f"{_ms(COMMAND_MATCH_S)} of these commands")
    return [Finding(
        title=f"{len(unlogged)} command(s) not sent by the test script (manual panel operation) during {names}",
        category="Operator / process",
        severity="Medium",
        confidence="Medium",
        symptom="The capture contains AZG/AZGH commands that do not appear in the test report.",
        evidence=evidence,
        root_cause="The test report lists every telegram the test script sends ('Sende ...'). These commands are "
                   "missing there, so they were most likely sent manually from the ESTW-ZE panel while the test was "
                   "running. Manual actions change the GFM-A outside the control of the test and are not documented.",
        potential_reasons=["Operator tried to recover the section during an automated preparation",
                           "Preparation instructions allow panel commands ('bei Bedarf')"],
        recommendation="Lock the panel while a test case is active or write every panel action into the test report; "
                       "train operators on the state-dependent recovery.",
        method="Matched every AZG/AZGH in the capture with the 'Sende ...' lines of the test report.",
        sources=["pcap", "pdf"],
        times=[command.time_s for command, _ in unlogged],
        frame_notes={command.frame: f"{command.label} not sent by the test script" for command, _ in unlogged},
        kind="unlogged_commands",
        facts={"commands": [(command.time_s, command.label, command.answered) for command, _ in unlogged]},
    )]


def rule_report(report: TestReport, capture: Optional[CaptureData]) -> List[Finding]:
    findings = []
    correlated = capture is not None and capture.offset_s is not None

    def state_at(time_s: float) -> Optional[StateReport]:
        if not correlated:
            return None
        section = capture.main_section()
        return capture.state_before(section, time_s + 0.001) if section else None

    def is_timeout(failure: ReportFailure) -> bool:
        text = failure.text.lower()
        return not text.startswith("cleanup") and any(
            key in text for key in ("zeitlimit", "nicht abgeschlossen", "timeout", "timed out"))

    timeouts = [(tc, f) for tc in report.test_cases for f in tc.failures if is_timeout(f)]
    if timeouts:
        evidence = []
        for tc, failure in timeouts:
            line = f"{failure.canoe_time_s:.3f} s: {tc.label} - {failure.text}"
            state = state_at(failure.canoe_time_s)
            if state:
                line += f" (GFM-A state then: {state.label} since {state.time_s:.3f} s)"
            evidence.append(line)
        numbers = ", ".join(dict.fromkeys(f"TC{tc.number}" for tc, _ in timeouts))
        findings.append(Finding(
            title=f"Preparation timed out: required GFM-A state not reached ({numbers})",
            category="Test execution / precondition",
            severity="High",
            confidence="High",
            symptom="The test report shows preparation timeouts: the test steps were never executed.",
            evidence=evidence,
            root_cause="The precondition could not be established within the time limit, so the affected test cases "
                       "failed before their first test step."
                       + (" See the GFM-A findings for why the state was not reached." if correlated else ""),
            recommendation="Let the preparation fail fast when the GFM-A reports 'gestört' and restore a defined state "
                           "before the test (state-aware recovery).",
            method="Read the failing steps of every test case in the CANoe report.",
            sources=["pdf"],
            times=[f.canoe_time_s for _, f in timeouts],
            report_notes={f.canoe_time_s: "precondition not reached (timeout)" for _, f in timeouts},
            kind="timeout",
            facts={"failures": [(f.canoe_time_s, f.text) for _, f in timeouts]},
        ))

    cleanups = [(tc, f) for tc in report.test_cases for f in tc.failures if f.text.lower().startswith("cleanup-ziel")
                or (f.text.lower().startswith("cleanup") and not any(g.text.lower().startswith("cleanup-ziel") for g in tc.failures))]
    if cleanups:
        evidence = [f"{f.canoe_time_s:.3f} s: {tc.label} - {f.text}" for tc, f in cleanups]
        if correlated:
            for tc, failure in cleanups:
                attempts = [c for c in capture.commands if failure.canoe_time_s - 10 <= c.time_s <= failure.canoe_time_s and not c.answered]
                evidence.extend(f"{c.label} at {c.time_s:.3f} s (frame {c.frame}) in state "
                                f"'{c.state_before.label if c.state_before else 'unknown'}': no reaction" for c in attempts)
        findings.append(Finding(
            title=f"Cleanup failed in {len(cleanups)} test case(s): next test started without a defined state",
            category="Test script logic",
            severity="High" if len(cleanups) > 1 else "Medium",
            confidence="High",
            symptom="The report states 'Cleanup fehlgeschlagen; definierter Ausgangszustand ... nicht garantiert'.",
            evidence=evidence,
            root_cause="The cleanup sends AZGH and waits a fixed time regardless of the GFM-A state. While the section "
                       "is 'gestört, nicht grundstellbar' the OC discards AZGH, so the cleanup cannot succeed.",
            recommendation="Make the cleanup state-aware and block the following test cases when it fails.",
            method="Read the cleanup results in the CANoe report and matched them with the commands in the capture.",
            sources=["pdf", "pcap"] if correlated else ["pdf"],
            times=[f.canoe_time_s for _, f in cleanups],
            report_notes={f.canoe_time_s: "cleanup failed" for _, f in cleanups},
            kind="cleanup",
            facts={"failures": [(f.canoe_time_s, f.text) for _, f in cleanups]},
        ))

    aborts = [(tc, f) for tc in report.test_cases for f in tc.failures
              if "aborted due to stop" in f.text.lower() or "execution stop" in f.text.lower()]
    if aborts:
        tc, failure = aborts[0]
        after_cleanup = bool(cleanups) and min(f.canoe_time_s for _, f in cleanups) < failure.canoe_time_s
        findings.append(Finding(
            title=f"TC{tc.number} inconclusive: test unit stopped manually",
            category="Operator / process",
            severity="Low",
            confidence="High",
            symptom=f"'{failure.text}' at {failure.canoe_time_s:.3f} s.",
            evidence=[f"{f.canoe_time_s:.3f} s: {t.label} - {f.text}" for t, f in aborts],
            root_cause="Not a failure of the object controller: the run was stopped by the tester"
                       + (", most likely because no defined start state was left after the failed cleanups." if after_cleanup else "."),
            recommendation="Let the framework block remaining test cases automatically ('no defined start state') "
                           "instead of a manual stop, and re-run the stopped test case separately.",
            method="Read the final entries of the CANoe report.",
            sources=["pdf"],
            times=[failure.canoe_time_s],
            report_notes={failure.canoe_time_s: "test unit stopped manually"},
            kind="manual_stop",
            facts={"failures": [(f.canoe_time_s, f.text) for _, f in aborts], "after_cleanup": after_cleanup},
        ))

    known = {id(f) for _, f in timeouts + cleanups + aborts}
    for tc in report.test_cases:
        others = [f for f in tc.failures if id(f) not in known and "cleanup" not in f.text.lower()
                  and "measurement stop" not in f.text.lower()]
        if others:
            findings.append(Finding(
                title=f"{tc.label}: test step failed",
                category="Test result",
                severity="Medium",
                confidence="High",
                symptom=others[0].text,
                evidence=[f"{f.canoe_time_s:.3f} s [{f.step or '-'}]: {f.text}" for f in others],
                root_cause="The step result differs from the expectation in the test specification.",
                recommendation="Compare the expected values of the step with the decoded telegrams at this time.",
                method="Read the failing steps of the CANoe report.",
                sources=["pdf"],
                times=[f.canoe_time_s for f in others],
                report_notes={f.canoe_time_s: "test step failed" for f in others},
                kind="step_failed",
                facts={"failures": [(f.canoe_time_s, f.step, f.text) for f in others]},
            ))
    return findings


# ---------------------------------------------------------------------------
# Document building
# ---------------------------------------------------------------------------

def _timezone(report: Optional[TestReport]) -> Optional[timezone]:
    if report and report.utc_offset:
        sign = 1 if report.utc_offset.startswith("+") else -1
        hours, minutes = report.utc_offset[1:].split(":")
        return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
    return None


def _short_id(test_case_id: str) -> str:
    parts = test_case_id.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else test_case_id


def analyze(capture_file: Optional[Tuple[str, bytes]], report_file: Optional[Tuple[str, bytes]]) -> dict:
    """Runs all rules on the uploaded files and returns an analysis-scenarios document."""
    report = read_report(report_file[1]) if report_file else None
    capture = decode_capture(capture_file[0], capture_file[1], _timezone(report)) if capture_file else None
    correlated = capture is None or capture.offset_s is not None

    findings: List[Finding] = []
    if capture:
        failure_times = [f.canoe_time_s for f in report.failures if f.canoe_time_s is not None] if report and correlated else []
        if not capture.frames:
            findings.append(Finding(
                title="No SCI-TDS/RaSTA traffic found in the capture",
                category="Data quality", severity="Medium", confidence="High",
                symptom="The capture contains no RaSTA PDUs.",
                evidence=[f"{capture.frame_count} frames, none decodable as RaSTA over UDP"],
                root_cause="The capture was taken on the wrong interface/VLAN or with a filter that removed the traffic.",
                recommendation="Capture the SCI-TDS interface (RaSTA over UDP) between ESTW-ZE and object controller.",
                method="Decoded all UDP datagrams with the RaSTA redundancy/safety layer.", sources=["pcap"],
            ))
        else:
            findings.append(rule_communication(capture))
            findings.extend(rule_disturbances(capture, failure_times))
            findings.extend(rule_inherited_state(capture, report))
            findings.extend(rule_commands(capture))
            findings.extend(rule_unused_window(capture))
            if report and correlated:
                findings.extend(rule_unlogged_commands(capture, report))
    if report:
        findings.extend(rule_report(report, capture))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], min(f.times) if f.times else float("inf")))
    for number, finding in enumerate(findings, 1):
        finding.id = f"S{number:02d}"
        if report and (correlated or finding.sources == ["pdf"]):
            ids = []
            for time_s in finding.times:
                tc = report.test_case_at(time_s)
                if tc and tc.test_case_id not in ids:
                    ids.append(tc.test_case_id)
            finding.test_cases = ids

    test_cases = _test_cases(report, findings) if report else []
    states = _state_history(capture, report if correlated else None, findings) if capture else []
    section = capture.main_section() if capture else None
    return {
        "source_file": " + ".join(name for name, _ in filter(None, (capture_file, report_file)))[:256],
        "title": _title(capture, report),
        "test_run": _test_run(capture, report, findings),
        "test_cases": test_cases,
        "scenarios": [_scenario(f) for f in findings],
        "timeline": _timeline(capture, report, findings, correlated),
        "gfma_state_history": {
            "section": section or "GFM-A",
            "coding_note": "Coding per SCI-TDS Baseline 5: Belegung 1=frei, 2=belegt, 3=gestört; Grundstellungsfähigkeit "
                           "0=nicht, 1=grundstellbar. Decoded from the uploaded capture." if section else None,
            "states": states,
        },
        "method": {"steps": _method_steps(capture, report), "open_questions": []},
        "io_graph": capture.io_graph if capture else None,
    }


def _title(capture: Optional[CaptureData], report: Optional[TestReport]) -> str:
    parts = []
    if report:
        parts.append(f"{report.test_unit or 'Test report'} {report.begin or ''}".strip())
    if capture:
        parts.append(f"capture {capture.file_name}")
    return "Upload analysis – " + " · ".join(parts)


def _test_run(capture: Optional[CaptureData], report: Optional[TestReport], findings: List[Finding]) -> dict:
    if report:
        counts = {v: sum(1 for tc in report.test_cases if tc.verdict == v) for v in ("Pass", "Fail", "Inconclusive")}
        verdict = (report.verdict or ("Fail" if counts["Fail"] else "Pass")).upper()
        overall = f"{verdict} – {counts['Pass']} Pass, {counts['Fail']} Fail, {counts['Inconclusive']} Inconclusive"
        if report.incomplete:
            overall += "; test unit stopped manually (incomplete)"
        name = ", ".join(filter(None, [report.test_unit, report.configuration, report.canoe_version, report.computer]))
    else:
        severe = sum(1 for f in findings if f.severity == "High")
        overall = f"Trace analysis only (no test report) – {len(findings)} findings, {severe} high severity"
        name = f"{capture.file_name}: {capture.frame_count} frames, {_secs(capture.duration_s)}"

    if capture and capture.frames:
        sections = sorted({s.section for s in capture.states})
        sut = f"Object controller {capture.oc_id or 'unknown'} at {capture.oc_ip}" + (f" (GFM-A {', '.join(sections)})" if sections else "")
        system = f"ESTW-ZE {capture.ze_id or 'unknown'} at {capture.ze_ip}, RaSTA/BTP over UDP {capture.port}"
    else:
        sut = "Not available - upload a capture to identify the object controller"
        system = "Not available - upload a capture to identify the ESTW-ZE"

    sources = []
    if capture:
        sources.append(f"{capture.file_name}: {capture.frame_count} frames, {len(capture.frames)} RaSTA PDUs, "
                       f"{sum(len(f.telegrams) for f in capture.frames)} SCI telegrams")
    if report:
        sources.append(f"CANoe test report: {len(report.test_cases)} test cases, {len(report.failures)} failing steps")

    if capture and report:
        correlation = (f"CANoe time = capture time + {capture.offset_s:.6f} s, derived from the RaSTA timestamps of the "
                       f"PDUs sent by CANoe (spread {capture.offset_spread_ms:.1f} ms)"
                       if capture.offset_s is not None else
                       "Capture and report could not be aligned (no CANoe timestamps in the RaSTA PDUs); times are shown per source")
    elif capture:
        correlation = (f"Times are CANoe measurement time (capture time + {capture.offset_s:.6f} s from RaSTA timestamps)"
                       if capture.offset_s is not None else "Times are seconds since the start of the capture")
    else:
        correlation = "Times are CANoe measurement time from the test report"
    return {"name": name or "Uploaded analysis", "overall_verdict": overall, "sut": sut, "test_system": system,
            "data_sources": "; ".join(sources), "time_correlation": correlation}


STATE_IN_TEXT = re.compile(r"(?:Belegungszustand|Zustand)=(\d)\D+?(?:Grundstellungsfaehigkeit|Grundstellbarkeit)=(\d)")
LIMIT_IN_TEXT = re.compile(r"(\d{4,})\s*ms")


def _step_name(step: Optional[str]) -> str:
    if not step:
        return "test step"
    if step.isdigit():
        return f"step {step}"
    return {"init": "preparation", "cleanup": "cleanup", "reset": "reset"}.get(step.lower(), step)


def _join(items: List[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _explain(tc: ReportTestCase, report: TestReport, findings: List[Finding]) -> str:
    """Plain-language explanation of why a test case did not pass, composed from the findings."""
    if tc.verdict == "Pass":
        return "Passed – no failing step in the report."

    def inside(time_s: Optional[float]) -> bool:
        return report.test_case_at(time_s) is tc

    def entries(kind: str) -> List[tuple]:
        return [entry for f in findings if f.kind == kind for entry in f.facts.get("failures", []) if inside(entry[0])]

    position = report.test_cases.index(tc)
    following = report.test_cases[position + 1] if position + 1 < len(report.test_cases) else None
    sentences: List[str] = []

    inherited = next((case for f in findings if f.kind == "inherited" for case in f.facts["cases"]
                      if case["test_case_id"] == tc.test_case_id), None)
    if inherited:
        sentences.append(
            f"Follow-up failure: {inherited['previous'] or 'the previous test'} left the GFM-A "
            f"'{inherited['state']}'" + (" and its cleanup failed" if inherited["cleanup_failed"] else "")
            + ", so this test started in a disturbed state.")
    disturbed = bool(inherited)
    for finding in (f for f in findings if f.kind == "disturbance"):
        facts = finding.facts
        if inside(facts["start_s"]):
            sentence = f"The GFM-A {facts['section']} switched to 'gestört' at {facts['start_s']:.3f} s"
            if facts.get("invalid"):
                sentence += f", {_ms(facts['delay_s'])} after an occupation with an invalid axle count (0x0000)"
            sentences.append(sentence + ".")
            disturbed = True
        elif not inherited and facts["start_s"] < tc.start_s <= facts["end_s"]:
            sentences.append(f"The GFM-A {facts['section']} was still 'gestört' (since {facts['start_s']:.3f} s).")
            disturbed = True
    for finding in (f for f in findings if f.kind == "missed_window" and inside(f.facts["start_s"])):
        sentences.append(f"It was 'grundstellbar' for {_secs(finding.facts['end_s'] - finding.facts['start_s'])}, "
                         "but no AZG/AZGH was sent to clear it.")
    for finding in (f for f in findings if f.kind == "unlogged_commands"):
        commands = [c for c in finding.facts["commands"] if inside(c[0])]
        if commands:
            verb = "were" if len(commands) > 1 else "was"
            outcome = "discarded as well" if not any(c[2] for c in commands) else "sent as well"
            sentences.append(f"{_join([c[1] for c in commands])} sent manually from the panel (not by the test script) "
                             f"{verb} {outcome}.")

    timeouts = entries("timeout")
    if timeouts:
        text = timeouts[0][1]
        state = next(filter(None, (STATE_IN_TEXT.search(t) for t in [text] + [f.text for f in tc.failures])), None)
        limit = LIMIT_IN_TEXT.search(text)
        sentence = "The required GFM-A state was never reached"
        if state and not disturbed:
            sentence += (f" (the GFM-A reported '{OCCUPANCY.get(int(state.group(1)), 'ungültig')}, "
                         f"{RESETTABLE.get(int(state.group(2)), 'ungültig')}')")
        sentence += f", so the preparation timed out{f' after {int(limit.group(1)) / 1000:g} s' if limit else ''}"
        sentences.append(sentence + " and the test steps were not executed.")
    cleanups = entries("cleanup")
    if cleanups:
        futile_times = [time_s for f in findings if f.kind == "futile_commands" for time_s in f.times]
        futile = any(entry[0] - 10 <= time_s <= entry[0] for entry in cleanups for time_s in futile_times)
        sentence = ("The cleanup AZGH was discarded because the section was not 'grundstellbar'" if futile
                    else "The cleanup failed")
        sentences.append(sentence + (f", so TC{following.number} started without a defined state." if following
                                     else ", so no defined state was left."))
    stops = entries("manual_stop")
    if stops:
        stop = next(f for f in findings if f.kind == "manual_stop")
        section = tc.failed_sections[0] if tc.failed_sections else None
        sentences.append(
            f"The tester stopped the test unit manually at {stops[0][0]:.3f} s" + (f" during '{section}'" if section else "")
            + (", most likely because the failed cleanup left no defined start state" if stop.facts.get("after_cleanup") else "")
            + ". The test is incomplete; this is not a failure of the object controller.")
    for time_s, step, text in entries("step_failed")[:2]:
        sentences.append(f"{_step_name(step).capitalize()} failed at {time_s:.3f} s: {text}")

    if not sentences:
        first = tc.failures[0] if tc.failures else None
        return first.text if first else "No failing step found in the report."
    return " ".join(sentences)


def _test_cases(report: TestReport, findings: List[Finding]) -> List[dict]:
    verdicts = {"Pass": "Pass", "Fail": "Fail", "Inconclusive": "Inconclusive", "None": "None", "Error in test system": "Error"}
    result = []
    for tc in report.test_cases:
        related = [f for f in findings if tc.test_case_id in f.test_cases]
        failure_point = None
        if tc.verdict != "Pass":
            first = tc.failures[0] if tc.failures else None
            section = tc.failed_sections[0] if tc.failed_sections else None
            where = f"{_step_name(first.step)}, {first.canoe_time_s:.3f} s" if first else None
            failure_point = " – ".join(filter(None, [section, where])) or None
        result.append({
            "number": tc.number,
            "test_case_id": tc.test_case_id,
            "variant": tc.variant or None,
            "title": None,
            "verdict": verdicts.get(tc.verdict, "None"),
            "window_start_s": round(tc.start_s, 3),
            "window_end_s": round(max(tc.end_s, tc.start_s), 3),
            "failure_point": failure_point[:4096] if failure_point else None,
            "root_cause": _explain(tc, report, findings)[:4096],
            "scenario_ids": [f.id for f in related],
        })
    return result


def _cap(lines: List[str]) -> List[str]:
    if len(lines) <= MAX_EVIDENCE_LINES:
        return lines
    return lines[:MAX_EVIDENCE_LINES - 1] + [f"… and {len(lines) - MAX_EVIDENCE_LINES + 1} more"]


def _scenario(finding: Finding) -> dict:
    labels = {"pcap": "pcap", "pdf": "PDF"}
    return {
        "id": finding.id,
        "title": finding.title[:4096],
        "category": finding.category,
        "test_cases": finding.test_cases,
        "test_case_scope": "All" if finding.applies_to_all else (", ".join(_short_id(t) for t in finding.test_cases) or None),
        "applies_to_all_test_cases": finding.applies_to_all,
        "data_sources": [{"type": source, "label": labels[source]} for source in finding.sources],
        "severity": finding.severity,
        "confidence": finding.confidence,
        "symptom": finding.symptom,
        "evidence": [line[:4096] for line in _cap(finding.evidence)],
        "root_cause": finding.root_cause,
        "potential_reasons": finding.potential_reasons,
        "recommendation": finding.recommendation,
        "method": finding.method,
    }


def _phase(report: Optional[TestReport], capture: Optional[CaptureData], time_s: float, correlated: bool) -> Tuple[str, Optional[str]]:
    if report and correlated:
        tc = report.test_case_at(time_s)
        if tc:
            return f"TC{tc.number} {_short_id(tc.test_case_id)}", tc.test_case_id
        if report.test_cases and time_s < report.test_cases[0].start_s:
            return "Pre-test", None
    if capture:
        session = next((s for s in capture.sessions if s.start_s <= time_s <= s.end_s + 1.0), None)
        if session:
            return f"RaSTA session {session.number}", None
    return "Outside test cases", None


def _timeline(capture: Optional[CaptureData], report: Optional[TestReport], findings: List[Finding], correlated: bool) -> List[dict]:
    frame_links: Dict[int, List[Tuple[str, str]]] = {}
    report_links: Dict[float, List[Tuple[str, str]]] = {}
    for finding in findings:
        for frame, note in finding.frame_notes.items():
            frame_links.setdefault(frame, []).append((finding.id, note))
        for time_s, note in finding.report_notes.items():
            report_links.setdefault(round(time_s, 6), []).append((finding.id, note))

    def comment(links: List[Tuple[str, str]]) -> Tuple[Optional[str], List[str]]:
        if not links:
            return None, []
        ids = sorted({i for i, _ in links})
        notes = "; ".join(dict.fromkeys(n for _, n in links))
        return f"{notes} – {', '.join(ids)}", ids

    events = []
    if capture:
        for frame in capture.frames:
            pdu = frame.pdu
            if pdu.pdu_type == DATA and frame.telegrams:
                text = ", ".join(t.describe() for t in frame.telegrams)
            elif pdu.pdu_type in (CONNECTION_REQUEST, CONNECTION_RESPONSE):
                text = f"RaSTA {pdu.type_name}, Version: {pdu.version}"
            elif pdu.pdu_type == DISCONNECT_REQUEST:
                text = f"RaSTA Disconnect Request: {DISCONNECT_REASONS.get(pdu.disconnect_reason, pdu.disconnect_reason)}"
            elif pdu.pdu_type in RETRANSMISSION_TYPES:
                text = f"RaSTA {pdu.type_name}"
            else:
                continue
            note, ids = comment(frame_links.get(frame.number, []))
            phase, test_case = _phase(report, capture, frame.time_s, correlated)
            events.append({
                "canoe_time_s": round(frame.time_s, 3), "wall_clock": frame.wall.strftime("%H:%M:%S.%f")[:12],
                "pcap_frame": frame.number, "source": "pcap", "direction": capture.direction(frame.src), "event": text[:4096],
                "phase": phase, "test_case_id": test_case, "comment": note, "scenario_ids": ids,
            })
        for number, time_s, src, _ in capture.icmp:
            note, ids = comment(frame_links.get(number, []))
            phase, test_case = _phase(report, capture, time_s, correlated)
            moment = capture.first_wall + timedelta(seconds=time_s - (capture.offset_s or 0.0))
            events.append({
                "canoe_time_s": round(max(time_s, 0.0), 3), "wall_clock": moment.strftime("%H:%M:%S.%f")[:12],
                "pcap_frame": number, "source": "pcap", "direction": "ZE host -> OC" if src == capture.ze_ip else f"{src} ->",
                "event": "Destination unreachable (Port unreachable)", "phase": phase, "test_case_id": test_case,
                "comment": note, "scenario_ids": ids,
            })
    if report:
        def wall_for(time_s: float) -> Optional[str]:
            if capture and capture.offset_s is not None:
                return (capture.first_wall + timedelta(seconds=time_s - capture.offset_s)).strftime("%H:%M:%S.%f")[:12]
            return None

        for tc in report.test_cases:
            events.append({
                "canoe_time_s": round(tc.start_s, 3), "wall_clock": wall_for(tc.start_s), "pcap_frame": None, "source": "pdf",
                "direction": None, "event": f"TC{tc.number} {tc.test_case_id} started (verdict {tc.verdict})",
                "phase": f"TC{tc.number} {_short_id(tc.test_case_id)}", "test_case_id": tc.test_case_id,
                "comment": None, "scenario_ids": [],
            })
        for failure in report.failures:
            if failure.canoe_time_s is None:
                continue
            tc = report.test_case_at(failure.canoe_time_s)
            note, ids = comment(report_links.get(round(failure.canoe_time_s, 6), []))
            events.append({
                "canoe_time_s": round(failure.canoe_time_s, 3), "wall_clock": wall_for(failure.canoe_time_s),
                "pcap_frame": None, "source": "pdf", "direction": None,
                "event": f"{failure.verdict}: {failure.text}"[:4096],
                "phase": f"TC{tc.number} {_short_id(tc.test_case_id)}" if tc else "Test unit",
                "test_case_id": tc.test_case_id if tc else None, "comment": note, "scenario_ids": ids,
            })
    events.sort(key=lambda e: (e["canoe_time_s"], e["source"] != "pdf"))
    if len(events) > MAX_TIMELINE_EVENTS:
        linked = [e for e in events if e["scenario_ids"] or e["source"] == "pdf"]
        others = [e for e in events if not (e["scenario_ids"] or e["source"] == "pdf")]
        others = others[:max(0, MAX_TIMELINE_EVENTS - len(linked))]
        events = sorted(linked + others, key=lambda e: (e["canoe_time_s"], e["source"] != "pdf"))[:MAX_TIMELINE_EVENTS]
    return events


def _state_history(capture: CaptureData, report: Optional[TestReport], findings: List[Finding]) -> List[dict]:
    section = capture.main_section()
    if section is None:
        return []
    notes: Dict[int, str] = {}
    for finding in findings:
        for frame, note in finding.frame_notes.items():
            notes.setdefault(frame, note)
    states = [s for s in capture.states if s.section == section]
    result = []
    for state, following in zip(states, states[1:] + [None]):
        if len(result) == MAX_STATE_EVENTS:
            break
        until = following.time_s if following else max(capture.end_s, state.time_s)
        phase, test_case = _phase(report, capture, state.time_s, report is not None)
        remark = notes.get(state.frame) or ("Aufrüst status" if state.initial else None)
        result.append({
            "canoe_time_s": round(state.time_s, 3), "pcap_frame": state.frame,
            "occupancy_code": state.occupancy, "occupancy": OCCUPANCY.get(state.occupancy, "ungültig"),
            "resettable_code": state.resettable, "resettable": RESETTABLE.get(state.resettable, "ungültig"),
            "axle_count": f"0x{state.axle_count:04X}",
            "duration_note": None if following else f"until end of capture ({until:.1f})",
            "phase": phase, "test_case_id": test_case, "remark": remark,
            "until_s": round(until, 3), "duration_s": round(until - state.time_s, 3),
        })
    return result


def _method_steps(capture: Optional[CaptureData], report: Optional[TestReport]) -> List[dict]:
    steps = []
    if capture:
        steps.append({"step": len(steps) + 1, "activity": "Decode the capture",
                      "details": "Read the pcapng/pcap frames, decoded RaSTA (redundancy and safety layer) and SCI-TDS "
                                 "telegrams with the Baseline 5 coding of the DB dissectors."})
    if report:
        steps.append({"step": len(steps) + 1, "activity": "Read the test report",
                      "details": "Extracted the CANoe report text and collected test cases, verdicts and failing steps."})
    if capture and report:
        steps.append({"step": len(steps) + 1, "activity": "Align the time bases",
                      "details": "Derived the CANoe time of every frame from the RaSTA timestamps of the PDUs sent by CANoe."})
    steps.append({"step": len(steps) + 1, "activity": "Apply the analysis rules",
                  "details": "Communication health, GFM-A disturbances, inherited states, command reactions, unused "
                             "recovery windows, preparation timeouts, cleanup failures and manual stops."})
    return steps
