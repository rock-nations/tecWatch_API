# tecWatch – Configurable Status and Post-Analysis API Layer

A configurable API layer for communication between **tecWatch**, **analysis components**, and the **DBLTAS Dashboard**.

## 🌟 Key Features

- **Zero-Code Server Switching**: Point to any remote tecWatch hardware or DBLTAS server simply by editing `config/config.yaml` or setting environment variables.
- **Validated Analysis Report Serving**: `GET /api/analysis` reads the configured analysis report JSON file on every request, validates it, and returns it unchanged to the Web GUI.
- **Analysis Findings API**: `GET /api/analysis/scenarios` serves the failure-analysis scenarios extracted from the data-analysis workbook: findings with evidence and recommendations, test-case verdicts, the correlated multi-source timeline, the GFM-A state history and the analysis method.
- **Upload & Analyze**: `POST /api/analysis/upload` analyses an uploaded SCI-TDS capture (pcapng/pcap) and/or CANoe test report (PDF): it decodes RaSTA/SCI-TDS telegrams, reads test cases and failing steps, aligns both time bases and explains in plain language why test cases failed. The result has the same format as the findings, so the Web GUI shows it with the same views.
- **Railway-Oriented tecWatch Status**: `GET /api/status` reports what the DB trial operator monitors: the SCI-TDS/RaSTA link between ESTW-ZE and object controller, GFM-A track-section states, the test unit and active alerts.
- **Dual Payload Formats (JSON & XML)**: Seamlessly accepts and generates both JSON (`application/json`) and XML (`application/xml`).
- **Comprehensive Multi-Tier Validation**:
  - **Message Length**: Enforces request size limits via ASGI middleware (`413 Payload Too Large`) and field length bounds.
  - **Mandatory Fields**: Strict requirement validation (`422 Unprocessable Entity`).
  - **Data Types**: Enforces strict typing without unwanted type coercion.
  - **Message Format**: Validates content type and structural schemas.
  - **Malformed Syntax Protection**: Safely catches invalid JSON or malformed XML (`400 Bad Request`).
  - **Unexpected Content**: Automatically rejects unauthorized/extra payload keys (`extra='forbid'`).
- **DBLTAS Dashboard Ready**: Includes CORS headers, OpenAPI / Swagger documentation (`/docs`), and ReDoc (`/redoc`).
- **Dynamic Configuration Reloading**: Reload target servers on the fly without restarting the process (`POST /api/config/reload`).
- **Built-in Mock Simulator**: Ready-to-use mock server for testing and local development.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    GUI["DBLTAS Dashboard"] -->|GET /api/status\nGET /api/analysis\nGET /api/analysis/scenarios\nPOST /api/analysis/upload| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    Gateway -->|capture + test report| Analyzer["Analysis engine\n(src/analyzer)"]
    Report[("Analysis report JSON\n(analysis.report_path)")] -->|read + validate\non every GET| Gateway
    Findings[("Analysis scenarios JSON\n(analysis.scenarios_path)")] -->|read + validate\non every GET| Gateway
    Workbook["Data-analysis workbook (.xlsx)"] -.->|scripts/extract_analysis_scenarios.py| Findings
    AnalysisComp["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured tecWatch / Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config/config.yaml"] -.->|Dynamic Settings| Gateway
```

On initial load the Web GUI calls `GET /api/status` (proxied to the configured tecWatch server) and `GET /api/analysis` (read from the analysis report file). Its **Analysis Findings** page calls `GET /api/analysis/scenarios`, and its **Upload & Analyze** page sends test-bench files to `POST /api/analysis/upload`. The GUI never posts analysis data; `POST /api/analysis` is for analysis components and forwards validated results to the configured target server.

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository (or navigate to backend folder)
git clone https://github.com/rock-nations/tecWatch_API.git
cd tecWatch_API

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (if not already installed)
pip install -r requirements.txt
```

### 2. Configuration (`config/config.yaml`)

```yaml
server:
  host: "192.168.1.10"       # Target tecWatch / DBLTAS backend host
  port: 8080                 # Target backend port
  timeout_seconds: 5.0       # Upstream request timeout

api:
  status_endpoint: "/api/status"      # Status endpoint
  result_endpoint: "/api/analysis"    # Post-analysis endpoint
  max_payload_bytes: 1048576          # 1 MB maximum payload length
  status_fallback: true               # tecWatch not reachable: GET /api/status returns the simulated status

analysis:
  report_path: "data/data-analysis-report.json"   # Report served by GET /api/analysis
  scenarios_path: "data/analysis-scenarios.json"  # Findings served by GET /api/analysis/scenarios
  max_report_bytes: 1048576                        # 1 MB maximum length of each analysis file
  max_upload_bytes: 52428800                       # 50 MB maximum size of each uploaded file (capture, test report)

gateway:
  listen_host: "0.0.0.0"
  listen_port: 8000
  log_level: "INFO"
  log_file: "logs/tecwatch_api.log"
```

> **Zero-Code Target Server Switching**:
> To connect to another server, change `server.host` and `server.port` in `config/config.yaml`, or set environment variables:
> ```bash
> export TECWATCH_SERVER_HOST="10.0.0.25"
> export TECWATCH_SERVER_PORT="9000"
> ```

> **Analysis Files**:
> Relative `analysis.report_path` / `analysis.scenarios_path` values are resolved against the backend folder; absolute paths work too. To serve other files, change the paths in `config/config.yaml` (then `POST /api/config/reload`) or set:
> ```bash
> export TECWATCH_ANALYSIS_REPORT_PATH="/path/to/data-analysis-report.json"
> export TECWATCH_ANALYSIS_SCENARIOS_PATH="/path/to/analysis-scenarios.json"
> ```
> Both files are read on every request, so regenerated files are served without restarting the API.

### 3. Running the API

```bash
source .venv/bin/activate
python -m src.main
```
Or with Uvicorn:
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive documentation is available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 API Usage Examples

### 1. GET Status (`/api/status`)

Proxied to the configured tecWatch server and validated. The status describes the monitored SCI-TDS interface of the test bench from the DB trial operator's perspective.

If the tecWatch server is not reachable (for example the mock server is not running or its port is blocked), the API returns its built-in status instead (the same status the mock server sends) with `"source": "simulated"`, so the Web GUI keeps working and shows a *Simulated* badge. A real tecWatch status carries `"source": "tecwatch"`. Turn this off with `api.status_fallback: false` in `config/config.yaml` or `TECWATCH_STATUS_FALLBACK=false`.

#### Request (JSON):
```bash
curl -G "http://localhost:8000/api/status" \
  --data-urlencode "device_id=DETHMM AZA34##0001" \
  -H "Accept: application/json"
```

**Response (JSON)** ([example](docs/examples/status_response.json), [XML](docs/examples/status_response.xml)):
```json
{
  "device_id": "DETHMM AZA34##0001",
  "status": "DEGRADED",
  "timestamp": "2026-10-07T07:30:00Z",
  "link": {
    "state": "CONNECTED",
    "protocol": "SCI-TDS Baseline 5 over RaSTA",
    "btp_version": "01",
    "version_check": "BTP-Versionswerte gleich",
    "local_endpoint": "DETHMM ZE 35##0001 (1.208.188.16:24001)",
    "remote_endpoint": "DETHMM AZA34##0001 (10.129.15.2:24001)",
    "heartbeat_interval_ms": 300,
    "last_message_at": "2026-10-07T07:29:59.880Z"
  },
  "track_sections": [
    {
      "section": "34W1",
      "section_type": "GFM-A",
      "occupancy": "DISTURBED",
      "resettable": false,
      "axle_count": 0,
      "since": "2026-10-02T10:27:06.906Z"
    }
  ],
  "test_execution": {
    "state": "STOPPED",
    "test_unit": "TDS-Test",
    "configuration": "ZE_RealOC_Stimulation.cfg",
    "current_test_case": "TC_NPRO.295.00522.01",
    "passed": 2,
    "failed": 2,
    "inconclusive": 1
  },
  "active_alerts": [
    "GFM-A 34W1 gestört (disturbed) and nicht grundstellbar: AZG/AZGH will be discarded",
    "Test unit stopped manually: TC_NPRO.295.00522.01 inconclusive"
  ]
}
```

| Field | Meaning |
| :--- | :--- |
| `device_id` | Technical ID of the monitored object controller (OC) |
| `status` | Overall state for the operator: `OPERATIONAL`, `DEGRADED`, `DISCONNECTED`, `FAULT` |
| `link` | RaSTA session state (`CONNECTED`, `CONNECTING`, `DISCONNECTED`), protocol/baseline, BTP version check, ESTW-ZE and OC endpoints, heartbeat interval, last message |
| `track_sections` | GFM-A sections: Belegungszustand (`FREE`, `OCCUPIED`, `DISTURBED`), Grundstellbarkeit (`resettable`), axle count, since when |
| `test_execution` | Test unit state (`IDLE`, `RUNNING`, `STOPPED`, `COMPLETED`), configuration, current test case, verdict counts |
| `active_alerts` | Alerts for the trial operator |

Add `-H "Accept: application/xml"` for the XML representation (`<tecWatchStatus>`). If tecWatch answers with data that fails validation, the API returns `502 Bad Gateway` with a `validation_errors` list.

---

### 2. GET Analysis Report (`/api/analysis`) - Web GUI Integration

Called by the DBLTAS Dashboard on initial load. The API reads the configured analysis report file, validates it, and returns it unchanged (format: [`data/data-analysis-report.json`](data/data-analysis-report.json)).

#### Request:
```bash
curl -s "http://localhost:8000/api/analysis"

# Same report as XML
curl -s "http://localhost:8000/api/analysis" -H "Accept: application/xml"
```

**Response (JSON, shortened)**:
```json
{
  "analysis_id": "TRACE-RUN-20261002-102359",
  "device_id": "DETHMM AZA34##0001",
  "timestamp": "2026-10-02T10:23:59.953Z",
  "analysis_type": "TRACE_COMMUNICATION",
  "result_status": "FAILED",
  "summary": "2 of 5 test cases failed. ...",
  "trace_messages": [
    {
      "message_id": "frame-380-2",
      "timestamp": "2026-10-02T10:27:00.241Z",
      "time_s": 180.287372,
      "sender": "34W1",
      "receiver": "DETHMM ZE 35##0001",
      "protocol": "SCI-TDS BL5 over RaSTA",
      "message_type": "MELDUNG_GFMA_BELEGUNGSZUSTAND",
      "message_code": "0x0007",
      "direction": "AZ→ZE",
      "length": 47,
      "fields": { "belegung": 1, "grundstellbar": 0, "achszaehlfuellstand": 0 },
      "test_case": "TC_NPRO.295.02288.01",
      "status": "FAILED",
      "error_reason": "Message Length Error"
    }
  ],
  "failure_findings": [
    {
      "message_id": "frame-380-2",
      "expected_length": 48,
      "actual_length": 47,
      "result": "Message Length Error",
      "test_case": "TC_NPRO.295.02288.01",
      "timestamp": "2026-10-02T10:27:00.241Z",
      "time_s": 180.287372,
      "category": "incorrect_length",
      "description": "Test_Description step 2 expects a 48-byte MELDUNG_GFMA_BELEGUNGSZUSTAND, the device sends 47 bytes: the step cannot pass",
      "confidence": 0.9,
      "evidence": ["TC_NPRO.295.02288.01_xcel.txt row 1", "RealOCWorking_TDS_21026.pcapng frame 380 telegram 2"]
    }
  ],
  "data_comparisons": [
    {
      "field": "Length MELDUNG_GFMA_BELEGUNGSZUSTAND (Test_Description step 2)",
      "expected": "48",
      "actual": "47",
      "result": "Error",
      "test_case": "TC_NPRO.295.02288.01"
    }
  ]
}
```

**Response when the report fails validation** (`500 Internal Server Error`):
```json
{
  "error": "Invalid Analysis Report",
  "detail": "Analysis report failed validation (check mandatory fields, data types, message length, or unexpected content).",
  "validation_errors": [
    {
      "field": "trace_messages -> 1 -> length",
      "type": "int_type",
      "message": "Invalid data type for field 'trace_messages -> 1 -> length': Input should be a valid integer"
    }
  ]
}
```
If the report file does not exist, the API answers `404 Not Found` with `"error": "Analysis Report Not Found"`.

---

### 3. GET Analysis Scenarios (`/api/analysis/scenarios`) - Analysis Findings Page

Returns the failure-analysis scenarios of a test run, extracted from the data-analysis workbook into [`data/analysis-scenarios.json`](data/analysis-scenarios.json). The file is read and validated on every request and returned unchanged.

```bash
curl -s "http://localhost:8000/api/analysis/scenarios"
```

| Key | Content |
| :--- | :--- |
| `test_run` | Test run, overall verdict, SUT, test system, data sources, time correlation |
| `test_cases` | Verdict, CANoe time window, failure point, most probable root cause and related scenarios per test case |
| `scenarios` | Findings (`S01`…): category, severity, confidence, data sources, symptom, evidence, root cause, potential reasons, recommendation, method |
| `timeline` | Correlated events from pcap, PDF report and BLF with CANoe time, wall clock, frame, direction and scenario references |
| `gfma_state_history` | GFM-A state changes (Belegungszustand, Grundstellungsfähigkeit, axle count) with durations |
| `method` | Reproducible analysis steps and open questions for the team |

Errors: `404 Not Found` (`"Analysis Scenarios Not Found"`) if the file is missing, `500` (`"Invalid Analysis Scenarios"`) with `validation_errors` if it is too large, malformed or fails the schema (`src/models/scenarios.py`), including unknown scenario or test-case references.

#### Regenerating the JSON from the workbook
```bash
pip install openpyxl   # only needed for the extraction script
python scripts/extract_analysis_scenarios.py "../TDS_Task/TDS_Task/SCI_TDS_Analysis_Scenarios_2026-10-02.xlsx"
```
The script locates columns by their header names, resolves short test-case references (e.g. `02288.01`) to full IDs, normalizes data sources and computes the GFM-A state durations (formula cells in the workbook).

---

### 4. POST Upload & Analyze (`/api/analysis/upload`) - Upload & Analyze Page

Analyses the files of a test run uploaded as `multipart/form-data`; send at least one of the two fields:

| Field | File | What is used |
| :--- | :--- | :--- |
| `capture` | SCI-TDS capture, `.pcapng` or `.pcap` (e.g. `RealOCWorking_TDS_21026.pcapng`) | RaSTA sessions, heartbeats, sequence numbers, disconnect reasons; SCI-TDS Baseline 5 telegrams (GFM-A states, AZG/AZGH, rejections, BTP version check) |
| `report` | CANoe test report exported as PDF (e.g. `Real_SCI-TDS_2026-10-02_12-24-11.pdf`) | Test unit, test cases with verdicts and time windows, failing steps, telegrams sent by the test script |

```bash
curl -s -X POST "http://localhost:8000/api/analysis/upload" \
  -F "capture=@RealOCWorking_TDS_21026.pcapng" \
  -F "report=@Real_SCI-TDS_2026-10-02_12-24-11.pdf"
```

The response has the format of `GET /api/analysis/scenarios`, plus an `io_graph` when a capture was uploaded: packets per interval (1 s for captures up to one hour) for all frames and for each IP address as sender (`ip.src`) and receiver (`ip.dst`), like the Wireshark I/O graph. The Web GUI draws it with an IP filter. Every test case that did not pass gets a plain-language `root_cause`, for example:

> The GFM-A 34W1 switched to 'gestört' at 186.952 s, 102 ms after an occupation with an invalid axle count (0x0000). It was 'grundstellbar' for 50.0 s, but no AZG/AZGH was sent to clear it. The required GFM-A state was never reached, so the preparation timed out after 120 s and the test steps were not executed. …

How it works (`src/analyzer/`):
1. **Capture** (`capture.py`, `sci.py`, `traffic.py`): reads pcapng/pcap (frame numbers as in Wireshark), decodes RaSTA redundancy/safety layer and SCI-TDS telegrams with the Baseline 5 coding of the DB dissectors, and counts packets per interval and IP address for the I/O graph.
2. **Report** (`report.py`): extracts the PDF text (pypdf) and reads test cases, verdicts, failing steps and the `Sende '…'` lines.
3. **Time alignment**: CANoe stamps the RaSTA PDUs it sends with its measurement time, so `CANoe time = capture time + offset` (median over all PDUs, accepted when the spread is below 5 ms).
4. **Rules** (`engine.py`): communication health, GFM-A disturbances and their trigger (occupation without valid axle count), test cases that start in a disturbed state, slow or missing reactions to AZG/AZGH, unused 'grundstellbar' windows, commands not sent by the test script, preparation timeouts, failed cleanups and manual stops.

Nothing is stored; the files are analysed in memory. Errors (`{"error", "detail"}`): `400` no file or empty file, `413` file larger than `analysis.max_upload_bytes`, `415` capture is not pcapng/pcap or report is not a PDF (checked by content), `422` damaged capture or PDF that is not a CANoe test report.

---

### 5. POST Analysis Result (`/api/analysis`)

Lets analysis components submit a result in the same structure as the analysis report. Accepts both JSON and XML. The result is validated and forwarded to the configured target server (`server` + `api.result_endpoint`); it does not replace the report served by `GET /api/analysis`. The Web GUI does not use this endpoint.

#### Request (JSON):
```bash
curl -X POST "http://localhost:8000/api/analysis" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  --data-binary @docs/examples/analysis_request.json
```

#### Request (XML):
```bash
curl -X POST "http://localhost:8000/api/analysis" \
  -H "Content-Type: application/xml" \
  -H "Accept: application/xml" \
  --data-binary @docs/examples/analysis_request.xml
```
In XML, repeated elements form lists (`<trace_messages>`, `<evidence>`) and empty elements (`<test_case/>`) mean `null`.

**Response (JSON)**:
```json
{
  "status": "SUCCESS",
  "message": "Post-analysis result validated and sent to target server",
  "analysis_id": "TRACE-RUN-20261002-102359",
  "processed_at": "2026-10-03T12:00:01Z"
}
```

---

### 6. Dynamic Configuration Inspection & Hot Reload

#### Check current configuration:
```bash
curl -X GET "http://localhost:8000/api/config"
```

#### Reload configuration at runtime (after editing `config/config.yaml`):
```bash
curl -X POST "http://localhost:8000/api/config/reload"
```

---

## 🛡️ Validation Rules & Failure Responses

The same schema (`src/models/analysis.py`) validates the report file served by `GET /api/analysis` and payloads sent to `POST /api/analysis`.

### POST `/api/analysis` (request payload)

| Validation Test | Status Code | Error Message / Details |
| :--- | :--- | :--- |
| **Payload > Max Size** | `413 Payload Too Large` | `"Request body size exceeds configured limit"` |
| **Missing Mandatory Field** | `422 Unprocessable Entity` | `"Mandatory field '<name>' is required but was not provided"` |
| **Invalid Data Type** | `422 Unprocessable Entity` | `"Invalid data type for field '<name>'"` |
| **Unexpected Content (Extra Keys)** | `422 Unprocessable Entity` | `"Unexpected field '<name>' is not permitted"` |
| **Invalid / Malformed JSON** | `400 Bad Request` | `"Malformed JSON syntax at line X, col Y"` |
| **Invalid / Malformed XML** | `400 Bad Request` | `"Invalid XML syntax or entity error"` |
| **Wrong Content-Type** | `415 Unsupported Media Type`| `"Unsupported Content-Type. Must be application/json or application/xml"` |

### GET `/api/analysis` (analysis report file)

| Validation Test | Status Code | Error Message / Details |
| :--- | :--- | :--- |
| **Report File Missing** | `404 Not Found` | `"Analysis report file '<name>' does not exist."` |
| **Report > `max_report_bytes`** | `500 Internal Server Error` | `"Analysis report exceeds the configured size limit (N bytes)."` |
| **Invalid / Malformed JSON, not UTF-8, not an object** | `500 Internal Server Error` | `"Malformed JSON syntax at line X, column Y: ..."` |
| **Schema Violations** (mandatory fields, data types, field lengths, unexpected content) | `500 Internal Server Error` | `validation_errors` list with the same messages as the POST table |

### GET `/api/analysis/scenarios` (analysis scenarios file)

Same checks as the report file (`404` if missing, `500` with `"error": "Invalid Analysis Scenarios"` otherwise). Additionally, scenario and test-case IDs must be unique and every reference (test case → scenarios, scenario → test cases, timeline, GFM-A states, open questions) must resolve.

### POST `/api/analysis/upload` (uploaded files)

| Validation Test | Status Code | Error |
| :--- | :--- | :--- |
| **No file in `capture` or `report`** | `400 Bad Request` | `"No File Uploaded"` |
| **Uploaded file is empty** | `400 Bad Request` | `"Empty File"` |
| **File > `analysis.max_upload_bytes`** (request > 2 × limit + 64 KiB is rejected by the middleware) | `413 Payload Too Large` | `"File Too Large"` / `"Payload Too Large"` |
| **Capture is not pcapng/pcap, report is not a PDF** (magic bytes, not the file name) | `415 Unsupported Media Type` | `"Unsupported File Type"` |
| **Damaged capture / PDF without CANoe test cases** | `422 Unprocessable Entity` | `"Unreadable Capture"` / `"Unreadable Test Report"` |

### GET `/api/status` (tecWatch response)

| Validation Test | Status Code | Error Message / Details |
| :--- | :--- | :--- |
| **tecWatch unreachable** (`api.status_fallback: true`, default) | `200 OK` | Built-in status with `"source": "simulated"` |
| **tecWatch unreachable** (`api.status_fallback: false`) | `502 Bad Gateway` | `"Cannot connect to target server ..."` |
| **tecWatch returns an error code** | `502 Bad Gateway` | `"Target server returned error code ..."` |
| **tecWatch timeout** (`api.status_fallback: false`) | `504 Gateway Timeout` | `"Connection to target server ... timed out"` |
| **Status fails validation** (mandatory fields, data types, allowed values, unexpected content) | `502 Bad Gateway` | `validation_errors` list |

### Report schema rules

- JSON values must already have the declared type: `"length": "47"` is rejected, timestamps must be ISO 8601 strings. (XML is untyped, so XML values are converted.)
- Enumerations: `result_status` ∈ `PASSED, FAILED, WARNING, INCONCLUSIVE`; trace `status` ∈ `OK, FAILED, WARNING`; comparison `result` ∈ `OK, Error, Warning`.
- Formats and ranges: `message_code` is hexadecimal (`0x0007`), `category` is snake_case, `confidence` is 0.0–1.0, lengths and `time_s` are non-negative.
- Consistency: trace `message_id` values are unique; a finding's `message_id` must reference a trace message; `expected_length` and `actual_length` are set together, and `actual_length` must equal the referenced message's `length`.

---

## 🧪 Running Automated Tests

Run the full automated test suite covering all validation rules, config switching, and API endpoints:

```bash
source .venv/bin/activate
pytest -v
```

The tests build small synthetic captures and report texts. If the test-bench files are present in `../TDS_Task/TDS_Task/`, the analysis is additionally checked against the real capture and PDF report.

---

## 📂 Project Structure

```text
tecwatch_api/
├── config/
│   ├── config.yaml          # Target server, API endpoints & analysis report configuration
│   └── settings.py          # Dynamic configuration loader & Pydantic models
├── data/
│   ├── data-analysis-report.json # Analysis report served by GET /api/analysis
│   └── analysis-scenarios.json   # Findings served by GET /api/analysis/scenarios
├── scripts/
│   └── extract_analysis_scenarios.py # Workbook (.xlsx) -> data/analysis-scenarios.json
├── src/
│   ├── main.py              # Application entrypoint & ASGI factory
│   ├── analyzer/
│   │   ├── capture.py       # pcapng/pcap reader, Ethernet/VLAN/IPv4/UDP/ICMP decoding
│   │   ├── sci.py           # RaSTA and SCI-TDS Baseline 5 decoding
│   │   ├── report.py        # CANoe test report (PDF) parser
│   │   ├── traffic.py       # Packets per interval and IP address (I/O graph)
│   │   └── engine.py        # Time alignment, analysis rules, result document
│   ├── api/
│   │   ├── routes.py        # /api/status, /api/analysis, /api/analysis/upload, /api/config endpoints
│   │   ├── middleware.py    # Payload size limiter & request logging
│   │   └── error_handlers.py# Standardized JSON/XML error handlers
│   ├── models/
│   │   ├── status.py        # Strict Pydantic models for status
│   │   ├── analysis.py      # Strict Pydantic models for the analysis report
│   │   └── scenarios.py     # Strict Pydantic models for the analysis scenarios
│   ├── services/
│   │   ├── analysis_report.py # Reads & validates the analysis report and scenarios files
│   │   ├── upload_analysis.py # Checks uploaded files and runs the analysis engine
│   │   ├── client.py        # Async upstream HTTP client
│   │   ├── xml_handler.py   # Safe XML parser and serializer (defusedxml)
│   │   └── mock_server.py   # Built-in mock tecWatch/DBLTAS server
│   └── utils/
│       └── logger.py        # Structured console & rotating file logging
├── tests/
│   ├── conftest.py          # Pytest fixtures & async test client
│   ├── test_config.py       # Server switching & reload tests
│   ├── test_validations.py  # 6-point validation test suite
│   ├── test_status_api.py   # Status endpoint unit/integration tests
│   ├── test_analysis_api.py # Analysis report (GET) & post-analysis (POST) tests
│   ├── test_scenarios_api.py # Analysis scenarios (GET) tests
│   ├── test_analyzer.py     # Capture/report decoding and analysis rules
│   ├── test_upload_api.py   # Upload & analyze endpoint tests
│   └── sample_files.py      # Synthetic pcapng / report builders for the tests
├── docs/
│   ├── api_documentation.md # Detailed specification document
│   └── examples/            # Sample JSON and XML payloads
├── requirements.txt         # Dependencies
├── pytest.ini               # Pytest configuration
└── README.md                # Documentation and running guide
```
