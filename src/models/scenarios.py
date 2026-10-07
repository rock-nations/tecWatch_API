from typing import Annotated, List, Literal, Optional
from pydantic import Field, StringConstraints, model_validator
from src.models.analysis import StrictModel

ScenarioId = Annotated[str, StringConstraints(pattern=r"^S\d{2,3}$")]
TestCaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
SourceType = Literal["pdf", "pcap", "blf", "write_log", "test_spec", "telegram_xlsx", "lua_dissector"]


class TestRunInfo(StrictModel):
    """Overview of the analysed test run."""

    name: Text = Field(..., description="Test run, tool version and configuration")
    overall_verdict: Text = Field(..., description="Overall verdict of the run")
    sut: Text = Field(..., description="System under test (object controller, GFM-A, address, baseline)")
    test_system: Text = Field(..., description="Test system (simulated ESTW-ZE, network, RaSTA/BTP)")
    data_sources: Text = Field(..., description="Data sources used for the analysis")
    time_correlation: Text = Field(..., description="How the time bases of the data sources were aligned")


class ScenarioTestCase(StrictModel):
    """Verdict and most probable root cause of one test case of the run."""

    number: int = Field(..., ge=1, description="Execution order")
    test_case_id: TestCaseId = Field(..., description="Test case ID (e.g. TC_NPRO.295.02288.01)")
    variant: Optional[ShortText] = Field(default=None, description="Variant suffix (e.g. O, F-ReZE)")
    title: Optional[Text] = Field(default=None, description="Short description of the test case")
    verdict: Literal["Pass", "Fail", "Inconclusive", "Error", "None"] = Field(..., description="Verdict in the test report")
    window_start_s: float = Field(..., ge=0, description="Start of the test case in CANoe time [s]")
    window_end_s: float = Field(..., ge=0, description="End of the test case in CANoe time [s]")
    failure_point: Optional[Text] = Field(default=None, description="Where the test case failed")
    root_cause: Text = Field(..., description="Most probable root cause")
    scenario_ids: List[ScenarioId] = Field(default_factory=list, description="Related analysis scenarios")


class DataSource(StrictModel):
    type: SourceType = Field(..., description="Normalized data source type")
    label: ShortText = Field(..., description="Data source as named in the analysis (e.g. BLF (system variables))")


class Scenario(StrictModel):
    """One analysis scenario / finding."""

    id: ScenarioId = Field(..., description="Scenario ID (e.g. S01)")
    title: Text = Field(..., description="Scenario / finding")
    category: ShortText = Field(..., description="Category (e.g. Test script logic)")
    test_cases: List[TestCaseId] = Field(default_factory=list, description="Test cases named in the scenario")
    test_case_scope: Optional[ShortText] = Field(default=None, description="Test case scope as written in the analysis")
    applies_to_all_test_cases: bool = Field(default=False, description="True if the scenario concerns the whole run")
    data_sources: List[DataSource] = Field(..., min_length=1, description="Data sources the finding is based on")
    severity: Literal["High", "Medium", "Low", "Info"] = Field(..., description="Severity")
    confidence: Literal["High", "Medium", "Low"] = Field(..., description="Confidence of the analysis")
    symptom: Text = Field(..., description="What the test report shows")
    evidence: List[Text] = Field(default_factory=list, description="Evidence (CANoe times, pcap frame numbers)")
    root_cause: Text = Field(..., description="Analysis / root cause")
    potential_reasons: List[Text] = Field(default_factory=list, description="Potential reasons")
    recommendation: Text = Field(..., description="Recommendation")
    method: Text = Field(..., description="How the finding was found")


class TimelineEvent(StrictModel):
    """Event of the correlated multi-source timeline."""

    canoe_time_s: float = Field(..., ge=0, description="CANoe measurement time [s]")
    wall_clock: Optional[Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}:\d{2}(\.\d+)?$")]] = Field(
        default=None, description="Local wall-clock time (null if it cannot be derived)"
    )
    pcap_frame: Optional[int] = Field(default=None, ge=1, description="pcap frame number")
    source: SourceType = Field(..., description="Data source of the event")
    direction: Optional[ShortText] = Field(default=None, description="Direction (e.g. ZE -> OC)")
    event: Text = Field(..., description="Event")
    phase: ShortText = Field(..., description="Test case or phase as written in the analysis")
    test_case_id: Optional[TestCaseId] = Field(default=None, description="Test case of the event")
    comment: Optional[Text] = Field(default=None, description="Analyst comment")
    scenario_ids: List[ScenarioId] = Field(default_factory=list, description="Scenarios referenced by the comment")


class SectionState(StrictModel):
    """State reported by the GFM-A (telegram 3.4.11) and how long it lasted."""

    canoe_time_s: float = Field(..., ge=0, description="CANoe time of the state report [s]")
    pcap_frame: Optional[int] = Field(default=None, ge=1, description="pcap frame number")
    occupancy_code: int = Field(..., ge=0, le=5, description="Belegungszustand (BL5: 1 frei, 2 belegt, 3 gestört, 0/4/5 other)")
    occupancy: ShortText = Field(..., description="Belegungszustand text")
    resettable_code: int = Field(..., ge=0, le=2, description="Grundstellungsfähigkeit (BL5: 0 nicht, 1 grundstellbar, 2 ungültig)")
    resettable: ShortText = Field(..., description="Grundstellungsfähigkeit text")
    axle_count: Annotated[str, StringConstraints(pattern=r"^0x[0-9A-Fa-f]{4}$")] = Field(
        ..., description="Axle count fill level (bytes 45-46)"
    )
    duration_note: Optional[ShortText] = Field(default=None, description="Note on the duration (e.g. until end)")
    phase: ShortText = Field(..., description="Test case or phase as written in the analysis")
    test_case_id: Optional[TestCaseId] = Field(default=None, description="Test case of the state report")
    remark: Optional[Text] = Field(default=None, description="Analyst remark")
    until_s: float = Field(..., ge=0, description="CANoe time when the state ended [s]")
    duration_s: float = Field(..., ge=0, description="Duration of the state [s]")


class SectionStateHistory(StrictModel):
    section: ShortText = Field(..., description="Track section (GFM-A)")
    coding_note: Optional[Text] = Field(default=None, description="Telegram coding used for the states")
    states: List[SectionState] = Field(default_factory=list, description="State changes in time order")


class MethodStep(StrictModel):
    step: int = Field(..., ge=1, description="Step number")
    activity: Text = Field(..., description="Activity")
    details: Text = Field(..., description="Details / commands")


class OpenQuestion(StrictModel):
    id: Annotated[str, StringConstraints(pattern=r"^Q\d+$")] = Field(..., description="Question ID (e.g. Q1)")
    question: Text = Field(..., description="Open question for the team")
    scenario_ids: List[ScenarioId] = Field(default_factory=list, description="Scenarios the question refers to")


class AnalysisMethod(StrictModel):
    steps: List[MethodStep] = Field(default_factory=list, description="Reproducible analysis steps")
    open_questions: List[OpenQuestion] = Field(default_factory=list, description="Open questions for the team")


PacketCount = Annotated[int, Field(ge=0)]


class IoGraphHost(StrictModel):
    """Packets one IP address sent and received per interval."""

    address: Annotated[str, StringConstraints(min_length=2, max_length=64)] = Field(..., description="IPv4 or IPv6 address")
    role: Optional[ShortText] = Field(default=None, description="Role on the SCI-TDS interface (e.g. ESTW-ZE (CANoe))")
    packets_sent: PacketCount = Field(..., description="Packets with this source address")
    packets_received: PacketCount = Field(..., description="Packets with this destination address")
    sent: List[PacketCount] = Field(..., description="Packets per interval with this source address (ip.src)")
    received: List[PacketCount] = Field(..., description="Packets per interval with this destination address (ip.dst)")


class IoGraph(StrictModel):
    """Packets per interval over an uploaded capture, like the Wireshark I/O graph."""

    capture_file: ShortText = Field(..., description="Capture the graph was built from")
    start_epoch_s: float = Field(..., ge=0, description="Time of the first packet (Unix time, UTC)")
    interval_s: float = Field(..., gt=0, description="Width of one interval [s]")
    utc_offset_min: Optional[int] = Field(
        default=None, ge=-14 * 60, le=14 * 60, description="UTC offset of the test bench (from the test report)"
    )
    canoe_zero_epoch_s: Optional[float] = Field(
        default=None, description="Unix time of CANoe measurement time 0 (null if the capture cannot be aligned)"
    )
    total_packets: PacketCount = Field(..., description="Frames in the capture")
    all_packets: List[PacketCount] = Field(..., min_length=1, description="All frames per interval")
    other_hosts: PacketCount = Field(default=0, description="Addresses not listed in hosts (only the busiest are listed)")
    hosts: List[IoGraphHost] = Field(default_factory=list, description="Busiest IP addresses, most packets first")

    @model_validator(mode="after")
    def intervals_match(self) -> "IoGraph":
        intervals = len(self.all_packets)
        for host in self.hosts:
            if len(host.sent) != intervals or len(host.received) != intervals:
                raise ValueError(f"io_graph host {host.address}: sent and received must have {intervals} intervals")
        return self


class AnalysisScenarios(StrictModel):
    """
    Failure-analysis scenarios (findings) of a test run, extracted from the data-analysis workbook
    and served by GET /api/analysis/scenarios, or computed from uploaded files by POST /api/analysis/upload.
    """

    source_file: ShortText = Field(..., description="Workbook the data was extracted from")
    title: Text = Field(..., description="Title of the analysis")
    test_run: TestRunInfo
    test_cases: List[ScenarioTestCase] = Field(default_factory=list)
    scenarios: List[Scenario] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    gfma_state_history: SectionStateHistory
    method: AnalysisMethod
    io_graph: Optional[IoGraph] = Field(default=None, description="Packets per interval of an uploaded capture")

    @model_validator(mode="after")
    def references_resolve(self) -> "AnalysisScenarios":
        scenario_ids = [scenario.id for scenario in self.scenarios]
        test_case_ids = [test_case.test_case_id for test_case in self.test_cases]
        problems = []

        for kind, ids in (("scenario id", scenario_ids), ("test_case_id", test_case_ids)):
            duplicates = sorted({value for value in ids if ids.count(value) > 1})
            if duplicates:
                problems.append(f"{kind} must be unique; duplicated: {', '.join(duplicates)}")

        def check(location: str, references: List[str], known: List[str], kind: str) -> None:
            for reference in references:
                if reference not in known:
                    problems.append(f"{location} references unknown {kind} '{reference}'")

        for index, test_case in enumerate(self.test_cases):
            check(f"test_cases[{index}]", test_case.scenario_ids, scenario_ids, "scenario")
        for index, scenario in enumerate(self.scenarios):
            check(f"scenarios[{index}]", scenario.test_cases, test_case_ids, "test case")
        for index, event in enumerate(self.timeline):
            check(f"timeline[{index}]", event.scenario_ids, scenario_ids, "scenario")
            check(f"timeline[{index}]", [event.test_case_id] if event.test_case_id else [], test_case_ids, "test case")
        for index, state in enumerate(self.gfma_state_history.states):
            check(
                f"gfma_state_history.states[{index}]",
                [state.test_case_id] if state.test_case_id else [], test_case_ids, "test case",
            )
        for index, question in enumerate(self.method.open_questions):
            check(f"method.open_questions[{index}]", question.scenario_ids, scenario_ids, "scenario")

        if problems:
            raise ValueError("; ".join(problems))
        return self
