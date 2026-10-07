# tecWatch Configurable Status & Post-Analysis API Documentation

## 1. Overview & Objective

The **tecWatch API** is a high-performance, configurable API layer designed for reliable communication between **tecWatch systems**, **analysis components**, and the **DBLTAS Dashboard**.

### Key Capabilities:
- **Zero-Code Server Switching**: Seamlessly re-point the API to different target servers simply by editing `config/config.yaml` or setting environment variables.
- **Dual Format Support**: Full support for both **JSON** and **XML** payloads.
- **Strict Multi-Tier Validation**:
  - Message-length validation (payload size limits and field bounds).
  - Mandatory field enforcement.
  - Strict data-type checking without loose coercion.
  - Schema & format validation.
  - Rejection of unexpected content / extra fields (`extra='forbid'`).
  - Graceful handling of invalid/malformed JSON and XML (`400 Bad Request`).
- **DBLTAS Dashboard Ready**:
  - Pre-configured CORS for browser clients.
  - Interactive Swagger UI at `/docs` and ReDoc at `/redoc`.
  - Validated analysis report endpoint providing trace messages, failure findings, and data comparisons for the dashboard.
  - Upload & analyze endpoint that explains failing test cases from an uploaded SCI-TDS capture and/or CANoe test report.

---

## 2. Architecture & Data Flow

```mermaid
flowchart LR
    GUI["DBLTAS Dashboard"] -->|GET /api/status\nGET /api/analysis\nGET /api/analysis/scenarios\nPOST /api/analysis/upload| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    Gateway -->|capture + test report| Analyzer["Analysis engine\n(src/analyzer)"]
    Report[("Analysis report JSON\n(analysis.report_path)")] -->|read + validate\non every GET| Gateway
    Findings[("Analysis scenarios JSON\n(analysis.scenarios_path)")] -->|read + validate\non every GET| Gateway
    Workbook["Data-analysis workbook (.xlsx)"] -.->|scripts/extract_analysis_scenarios.py| Findings
    Analysis["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured tecWatch / Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config.yaml / Env Vars"] -.->|Dynamic Settings| Gateway
```

1. On initial load the Web GUI calls `GET /api/status` and `GET /api/analysis`.
2. `GET /api/status` is proxied to the configured tecWatch server and validated.
3. `GET /api/analysis` reads the configured analysis report file (produced by the data-analysis component), validates it, and returns it unchanged.
4. The GUI's **Analysis Findings** page calls `GET /api/analysis/scenarios`, which serves the failure-analysis scenarios extracted from the data-analysis workbook (read and validated on every request, returned unchanged).
5. The GUI's **Upload & Analyze** page sends a capture (pcapng/pcap) and/or CANoe test report (PDF) to `POST /api/analysis/upload`; the backend analyses them in memory and returns findings in the scenarios format.
6. Analysis components may submit results with `POST /api/analysis`; they are validated and forwarded to the configured target server. The Web GUI never posts analysis data.

---

## 3. Configuration Mechanism

The server connection is controlled dynamically by `config/config.yaml`. To switch target servers, you simply change the configuration file:

```yaml
server:
  host: "192.168.1.10"       # Target tecWatch / DBLTAS backend host
  port: 8080                 # Target backend port
  timeout_seconds: 5.0       # Timeout for upstream requests

api:
  status_endpoint: "/api/status"      # Endpoint to fetch status
  result_endpoint: "/api/analysis"    # Endpoint to send analysis results
  max_payload_bytes: 1048576          # 1 MB maximum allowed request size

analysis:
  report_path: "data/data-analysis-report.json"   # Report served by GET /api/analysis (relative to the backend folder)
  scenarios_path: "data/analysis-scenarios.json"  # Findings served by GET /api/analysis/scenarios
  max_report_bytes: 1048576                        # 1 MB maximum length of each analysis file
  max_upload_bytes: 52428800                       # 50 MB maximum size of each file uploaded for analysis

gateway:
  listen_host: "0.0.0.0"     # Interface where this API binds
  listen_port: 8000          # Port where this API listens
  log_level: "INFO"          # Logging level (DEBUG, INFO, WARNING, ERROR)
  log_file: "logs/tecwatch_api.log"
```

### Environment Variable Overrides
Configuration values can also be set via environment variables without touching configuration files:
- `TECWATCH_SERVER_HOST`: Overrides `server.host`
- `TECWATCH_SERVER_PORT`: Overrides `server.port`
- `TECWATCH_STATUS_ENDPOINT`: Overrides `api.status_endpoint`
- `TECWATCH_RESULT_ENDPOINT`: Overrides `api.result_endpoint`
- `TECWATCH_ANALYSIS_REPORT_PATH`: Overrides `analysis.report_path`
- `TECWATCH_ANALYSIS_SCENARIOS_PATH`: Overrides `analysis.scenarios_path`

### Live Configuration Reload
You can reload configuration at runtime without restarting the service by issuing:
```http
POST /api/config/reload
```

---

## 4. API Endpoints

### 4.1 GET Status API (`/api/status`)
Retrieves the current status of the monitored SCI-TDS interface from the configured upstream tecWatch server and validates it. The status is designed for the DB trial operator: is the RaSTA link to the object controller up, which state do the GFM-A sections report, what is the test unit doing, and which alerts are active.

- **URL**: `/api/status`
- **Method**: `GET`
- **Query Parameters**:
  - `device_id` *(optional, string, 1-64 chars)*: Technical ID of the object controller (e.g. `DETHMM AZA34##0001`, URL-encoded).

#### Request Example:
```http
GET /api/status?device_id=DETHMM%20AZA34%23%230001 HTTP/1.1
Host: localhost:8000
Accept: application/json
```

#### JSON Response (`Accept: application/json`):
```http
HTTP/1.1 200 OK
Content-Type: application/json

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

#### Status Fields:
| Field | Type | Description |
| :--- | :--- | :--- |
| `device_id` | string | Technical ID of the monitored object controller |
| `status` | string | `OPERATIONAL`, `DEGRADED`, `DISCONNECTED` or `FAULT` |
| `timestamp` | string (ISO 8601) | Time of the status |
| `link.state` | string | RaSTA session: `CONNECTED`, `CONNECTING` or `DISCONNECTED` |
| `link.protocol`, `link.btp_version`, `link.version_check` | string | Protocol and baseline, negotiated BTP version, result of the version check |
| `link.local_endpoint`, `link.remote_endpoint` | string | ESTW-ZE and object controller (technical ID and address) |
| `link.heartbeat_interval_ms`, `link.last_message_at` | integer, string | RaSTA heartbeat interval, last received message |
| `track_sections[].section`, `section_type` | string | Section name (e.g. `34W1`) and type (`GFM-A`) |
| `track_sections[].occupancy` | string | Belegungszustand: `FREE`, `OCCUPIED` or `DISTURBED` |
| `track_sections[].resettable` | boolean | Grundstellbarkeit: `true` if AZG/AZGH would be accepted |
| `track_sections[].axle_count`, `since` | integer, string | Axle count fill level, since when the state is reported |
| `test_execution` | object | `state` (`IDLE`, `RUNNING`, `STOPPED`, `COMPLETED`), `test_unit`, `configuration`, `current_test_case`, `passed`, `failed`, `inconclusive` |
| `active_alerts` | array of strings | Alerts for the trial operator |

#### XML Response (`Accept: application/xml`):
```http
HTTP/1.1 200 OK
Content-Type: application/xml

<?xml version="1.0" encoding="UTF-8"?>
<tecWatchStatus>
  <device_id>DETHMM AZA34##0001</device_id>
  <status>DEGRADED</status>
  <timestamp>2026-10-07T07:30:00Z</timestamp>
  <link>
    <state>CONNECTED</state>
    <protocol>SCI-TDS Baseline 5 over RaSTA</protocol>
    <btp_version>01</btp_version>
    <version_check>BTP-Versionswerte gleich</version_check>
    <local_endpoint>DETHMM ZE 35##0001 (1.208.188.16:24001)</local_endpoint>
    <remote_endpoint>DETHMM AZA34##0001 (10.129.15.2:24001)</remote_endpoint>
    <heartbeat_interval_ms>300</heartbeat_interval_ms>
    <last_message_at>2026-10-07T07:29:59.880Z</last_message_at>
  </link>
  <track_sections>
    <section>34W1</section>
    <section_type>GFM-A</section_type>
    <occupancy>DISTURBED</occupancy>
    <resettable>false</resettable>
    <axle_count>0</axle_count>
    <since>2026-10-02T10:27:06.906Z</since>
  </track_sections>
  <test_execution>
    <state>STOPPED</state>
    <test_unit>TDS-Test</test_unit>
    <configuration>ZE_RealOC_Stimulation.cfg</configuration>
    <current_test_case>TC_NPRO.295.00522.01</current_test_case>
    <passed>2</passed>
    <failed>2</failed>
    <inconclusive>1</inconclusive>
  </test_execution>
  <active_alerts>GFM-A 34W1 gestört (disturbed) and nicht grundstellbar: AZG/AZGH will be discarded</active_alerts>
  <active_alerts>Test unit stopped manually: TC_NPRO.295.00522.01 inconclusive</active_alerts>
</tecWatchStatus>
```

---

### 4.2 GET Analysis Report API (`/api/analysis`)
Called by the DBLTAS Dashboard on initial load. Reads the configured analysis report file (`analysis.report_path`), validates it (message length, message format, mandatory fields, data types, unexpected content, consistency) and returns it **unchanged**. The file is read on every request, so a regenerated report is served without restarting the API.

- **URL**: `/api/analysis`
- **Method**: `GET`
- **Supported Headers**:
  - `Accept`: `application/json` (default) or `application/xml`

#### Request Example:
```http
GET /api/analysis HTTP/1.1
Host: localhost:8000
Accept: application/json
```

#### JSON Response (shortened, full example: `data/data-analysis-report.json`):
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "analysis_id": "TRACE-RUN-20261002-102359",
  "device_id": "DETHMM AZA34##0001",
  "timestamp": "2026-10-02T10:23:59.953Z",
  "analysis_type": "TRACE_COMMUNICATION",
  "result_status": "FAILED",
  "summary": "2 of 5 test cases failed. ...",
  "trace_messages": [ { "message_id": "frame-380-2", "length": 47, "status": "FAILED", "error_reason": "Message Length Error", ... } ],
  "failure_findings": [ { "message_id": "frame-380-2", "expected_length": 48, "actual_length": 47, "result": "Message Length Error", ... } ],
  "data_comparisons": [ { "field": "Test verdict", "expected": "PASSED", "actual": "FAILED", "result": "Error", "test_case": "TC_NPRO.295.02288.01" } ]
}
```

#### Error Responses:
| Situation | Status | `error` |
| :--- | :--- | :--- |
| Report file does not exist | `404 Not Found` | `Analysis Report Not Found` |
| Report too large, unreadable, not UTF-8, malformed JSON, not a JSON object | `500 Internal Server Error` | `Invalid Analysis Report` |
| Report violates the schema (see section 5) | `500 Internal Server Error` | `Invalid Analysis Report` (+ `validation_errors`) |

---

### 4.3 POST Analysis Result API (`/api/analysis`)
Lets analysis components submit a result in the analysis report format (section 5), as JSON or XML. Validates message length, mandatory fields, data types, and rejects unexpected content, then forwards the validated result to the configured target server (`server` + `api.result_endpoint`). A posted result does not replace the report served by `GET /api/analysis`, and the Web GUI does not call this endpoint.

- **URL**: `/api/analysis`
- **Method**: `POST`
- **Supported Headers**:
  - `Content-Type`: `application/json` or `application/xml`
  - `Accept`: `application/json` or `application/xml`

#### Request Examples:
- JSON: [`examples/analysis_request.json`](examples/analysis_request.json)
- XML: [`examples/analysis_request.xml`](examples/analysis_request.xml) (repeated elements form lists, empty elements such as `<test_case/>` mean `null`; values are converted to the declared types)

```http
POST /api/analysis HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Accept: application/json

{ ...content of examples/analysis_request.json... }
```

#### JSON Response:
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "SUCCESS",
  "message": "Post-analysis result validated and sent to target server",
  "analysis_id": "TRACE-RUN-20261002-102359",
  "processed_at": "2026-10-03T12:00:01Z"
}
```

---

### 4.4 GET Analysis Scenarios API (`/api/analysis/scenarios`)
Called by the Web GUI's **Analysis Findings** page. Reads the configured analysis scenarios file (`analysis.scenarios_path`, default `data/analysis-scenarios.json`), validates it against `src/models/scenarios.py` and returns it unchanged. The file is generated from the data-analysis workbook with `scripts/extract_analysis_scenarios.py`.

- **URL**: `/api/analysis/scenarios`
- **Method**: `GET`
- **Supported Headers**: `Accept`: `application/json` (default) or `application/xml`

#### Response Structure:
| Key | Content |
| :--- | :--- |
| `source_file`, `title` | Workbook the data was extracted from, title of the analysis |
| `test_run` | `name`, `overall_verdict`, `sut`, `test_system`, `data_sources`, `time_correlation` |
| `test_cases[]` | `number`, `test_case_id`, `variant`, `title`, `verdict` (`Pass`, `Fail`, `Inconclusive`, `Error`, `None`), `window_start_s`, `window_end_s`, `failure_point`, `root_cause`, `scenario_ids` |
| `scenarios[]` | `id` (`S01`…), `title`, `category`, `test_cases`, `test_case_scope`, `applies_to_all_test_cases`, `data_sources[]` (`type`: `pdf`, `pcap`, `blf`, `write_log`, `test_spec`, `telegram_xlsx`, `lua_dissector`; `label`), `severity` (`High`, `Medium`, `Low`, `Info`), `confidence` (`High`, `Medium`, `Low`), `symptom`, `evidence[]`, `root_cause`, `potential_reasons[]`, `recommendation`, `method` |
| `timeline[]` | `canoe_time_s`, `wall_clock`, `pcap_frame`, `source`, `direction`, `event`, `phase`, `test_case_id`, `comment`, `scenario_ids` |
| `gfma_state_history` | `section`, `coding_note`, `states[]` (`canoe_time_s`, `pcap_frame`, `occupancy_code`/`occupancy`, `resettable_code`/`resettable`, `axle_count`, `until_s`, `duration_s`, `duration_note`, `phase`, `test_case_id`, `remark`) |
| `method` | `steps[]` (`step`, `activity`, `details`), `open_questions[]` (`id`, `question`, `scenario_ids`) |

#### Error Responses:
| Situation | Status | `error` |
| :--- | :--- | :--- |
| Scenarios file does not exist | `404 Not Found` | `Analysis Scenarios Not Found` |
| File too large, unreadable, not UTF-8, malformed JSON, not a JSON object | `500 Internal Server Error` | `Invalid Analysis Scenarios` |
| Schema violation or unresolved reference (unknown scenario/test case, duplicate IDs) | `500 Internal Server Error` | `Invalid Analysis Scenarios` (+ `validation_errors`) |

---

### 4.5 POST Upload & Analyze API (`/api/analysis/upload`)
Called by the Web GUI's **Upload & Analyze** page. Analyses the uploaded files of a test run in memory (nothing is stored) and returns the result in the format of `GET /api/analysis/scenarios` (section 4.4).

- **URL**: `/api/analysis/upload`
- **Method**: `POST`
- **Content-Type**: `multipart/form-data` with at least one of:
  - `capture`: SCI-TDS capture as `.pcapng` or `.pcap` (Ethernet with or without VLAN tags, raw IP, Linux SLL)
  - `report`: CANoe test report exported as PDF
- **Supported Headers**: `Accept`: `application/json` (default) or `application/xml`

#### Request Example:
```bash
curl -s -X POST "http://localhost:8000/api/analysis/upload" \
  -F "capture=@RealOCWorking_TDS_21026.pcapng" \
  -F "report=@Real_SCI-TDS_2026-10-02_12-24-11.pdf"
```

#### Processing:
| Step | Details |
| :--- | :--- |
| Capture decoding | pcapng/pcap blocks (frame numbers as in Wireshark, CANoe Custom Blocks included), Ethernet/VLAN/IPv4/UDP, RaSTA redundancy + safety layer (connection, heartbeat, data, retransmission, disconnect), SCI-TDS Baseline 5 telegrams (GFM-A Belegungszustand, AZG, AZGH, Kommando abgewiesen, AZGH-Quittung, Aufrüstung, BTP version check) |
| Report reading | Test unit, begin/end with UTC offset, configuration, test cases with verdict and time window, failing steps with step and section, telegrams sent by the test script (`Sende '…'`) |
| Time alignment | CANoe writes its measurement time (µs) into the RaSTA timestamp of the PDUs it sends: `CANoe time = capture time + offset` (median; accepted when the median deviation is ≤ 5 ms). Without it, capture and report findings are not mapped to test cases. |
| Rules | Communication health (unanswered connections, abnormal disconnects, failed BTP version check, retransmissions, sequence gaps, message gaps > 750 ms); GFM-A 'gestört' episodes and their trigger (occupation with axle count 0x0000); test cases starting in a disturbed state; reactions to AZG/AZGH slower than 500 ms or missing; recovery commands while not 'grundstellbar'; unused 'grundstellbar' windows; commands not sent by the test script; preparation timeouts; failed cleanups; manual stops; other failing steps |
| Result | `test_cases[].root_cause` explains each failed or inconclusive test case in plain language; `scenarios` are sorted by severity (`S01` = most severe); `timeline` (max. 400 events) and `gfma_state_history` are built from the decoded data |

#### Error Responses:
| Situation | Status | `error` |
| :--- | :--- | :--- |
| Neither `capture` nor `report` sent | `400 Bad Request` | `No File Uploaded` |
| An uploaded file is empty | `400 Bad Request` | `Empty File` |
| A file is larger than `analysis.max_upload_bytes` | `413 Payload Too Large` | `File Too Large` |
| The request is larger than 2 × `max_upload_bytes` + 64 KiB (`Content-Length`) | `413 Payload Too Large` | `Payload Too Large` |
| `capture` is not pcapng/pcap or `report` is not a PDF (checked by content) | `415 Unsupported Media Type` | `Unsupported File Type` |
| Damaged capture, unreadable PDF, PDF without CANoe test cases, more than 400 pages | `422 Unprocessable Entity` | `Unreadable Capture` / `Unreadable Test Report` |

---

## 5. Analysis Report Format

Defined in `src/models/analysis.py`. Fields marked *optional* may be omitted (lists default to `[]`, `fields` to `{}`, nullable values to `null`). Any field not listed here is rejected as unexpected content.

### Report (top level)
| Field | Type | Required | Constraints |
| :--- | :--- | :--- | :--- |
| `analysis_id` | string | yes | 3–64 characters |
| `device_id` | string | yes | 1–64 characters |
| `timestamp` | string (ISO 8601) | yes | |
| `analysis_type` | string | yes | 2–64 characters |
| `result_status` | string | yes | `PASSED`, `FAILED`, `WARNING`, `INCONCLUSIVE` |
| `summary` | string | yes | 1–4096 characters |
| `trace_messages` | array of trace messages | optional | `message_id` values unique |
| `failure_findings` | array of failure findings | optional | |
| `data_comparisons` | array of data comparisons | optional | |

### Trace message (`trace_messages[]`)
| Field | Type | Required | Constraints |
| :--- | :--- | :--- | :--- |
| `message_id` | string | yes | 1–64 characters, unique |
| `timestamp` | string (ISO 8601) | yes | |
| `time_s` | number | yes | ≥ 0 (seconds since trace start) |
| `sender`, `receiver` | string | yes | 1–64 characters |
| `protocol`, `message_type` | string | yes | 1–64 characters |
| `message_code` | string | yes | hexadecimal, e.g. `0x0007` |
| `direction` | string | yes | 1–32 characters, e.g. `AZ→ZE` |
| `length` | integer | yes | ≥ 0 (bytes) |
| `fields` | object | optional | keys 1–64 characters; values string (≤ 256), number, boolean or `null` |
| `test_case` | string or `null` | optional | 1–64 characters |
| `status` | string | yes | `OK`, `FAILED`, `WARNING` |
| `error_reason` | string or `null` | optional | 1–256 characters |

### Failure finding (`failure_findings[]`)
| Field | Type | Required | Constraints |
| :--- | :--- | :--- | :--- |
| `message_id` | string or `null` | optional | must reference a trace message |
| `expected_length` | integer or `null` | optional | ≥ 0; set together with `actual_length` |
| `actual_length` | integer or `null` | optional | ≥ 0; equals the referenced trace message `length` |
| `result` | string | yes | 1–64 characters, e.g. `Message Length Error` |
| `test_case` | string or `null` | optional | 1–64 characters |
| `timestamp` | string (ISO 8601) | yes | |
| `time_s` | number | yes | ≥ 0 |
| `category` | string | yes | snake_case, e.g. `incorrect_length` |
| `description` | string | yes | 1–1024 characters |
| `confidence` | number | yes | 0.0–1.0 |
| `evidence` | array of strings | optional | each 1–256 characters |

### Data comparison (`data_comparisons[]`)
| Field | Type | Required | Constraints |
| :--- | :--- | :--- | :--- |
| `field` | string | yes | 1–128 characters |
| `expected`, `actual` | string | yes | ≤ 256 characters |
| `result` | string | yes | `OK`, `Error`, `Warning` |
| `test_case` | string or `null` | optional | `null` for trace-wide checks |

---

## 6. Validation Specification

### 6.1 POST `/api/analysis` request payload
| Validation Check | Mechanism | Failure Code | Error Details |
| :--- | :--- | :--- | :--- |
| **Message Length (Total)** | ASGI middleware checks `Content-Length` | `413 Payload Too Large` | Size in bytes exceeds `max_payload_bytes` |
| **Message Length (Fields)** | Pydantic `min_length` & `max_length` | `422 Unprocessable Entity` | Field value string length out of bounds |
| **Mandatory Fields** | Pydantic required fields | `422 Unprocessable Entity` | `Mandatory field '<field>' is required` |
| **Data Types** | Strict Pydantic model (`strict=True`; JSON `"47"` is not an integer) | `422 Unprocessable Entity` | `Invalid data type for field '<field>'` |
| **Message Format** | Content-Type checking | `415 Unsupported Media Type` | Unsupported format (not JSON or XML) |
| **Invalid JSON** | Intercepts `JSONDecodeError` | `400 Bad Request` | `Malformed JSON syntax at line X, col Y` |
| **Invalid XML** | `defusedxml` parser | `400 Bad Request` | `Invalid XML syntax or entity error` |
| **Unexpected Content** | Pydantic `extra = 'forbid'`, enumerations, patterns | `422 Unprocessable Entity` | `Unexpected field '<field>' is not permitted` |
| **Consistency** | Model validators (see 6.5) | `422 Unprocessable Entity` | e.g. `message_id 'x' does not match any trace message` |

### 6.2 GET `/api/analysis` report file
| Validation Check | Mechanism | Failure Code | Error Details |
| :--- | :--- | :--- | :--- |
| **File Exists** | File read | `404 Not Found` | `Analysis report file '<name>' does not exist.` |
| **Message Length (Total)** | At most `max_report_bytes` are read | `500 Internal Server Error` | `Analysis report exceeds the configured size limit (N bytes).` |
| **Message Format** | UTF-8 JSON object | `500 Internal Server Error` | `Malformed JSON syntax at line X, column Y`, `must be a JSON object` |
| **Schema** (lengths, mandatory fields, data types, unexpected content, consistency) | Same model as POST | `500 Internal Server Error` | `validation_errors` list as in section 7 |

### 6.3 GET `/api/analysis/scenarios` scenarios file
Same file checks as 6.2 with `"error": "Invalid Analysis Scenarios"` / `"Analysis Scenarios Not Found"`. Scenario and test-case IDs must be unique and every reference must resolve (test cases → scenarios, scenarios → test cases, timeline events, GFM-A states, open questions).

### 6.4 POST `/api/analysis/upload` files
| Validation Check | Mechanism | Failure Code | Error |
| :--- | :--- | :--- | :--- |
| **Message Length (Request)** | `Content-Length` ≤ 2 × `max_upload_bytes` + 64 KiB (middleware) | `413 Payload Too Large` | `Payload Too Large` |
| **Message Length (File)** | At most `max_upload_bytes` are read per file | `413 Payload Too Large` | `File Too Large` |
| **Mandatory Content** | At least one non-empty file | `400 Bad Request` | `No File Uploaded`, `Empty File` |
| **Message Format** | pcapng/pcap and PDF magic bytes per field | `415 Unsupported Media Type` | `Unsupported File Type` |
| **Content** | Capture blocks and PDF text must be decodable; the report must contain test cases | `422 Unprocessable Entity` | `Unreadable Capture`, `Unreadable Test Report` |
| **Result** | The generated document is validated against `src/models/scenarios.py` | `500 Internal Server Error` | `Analysis Failed` |

### 6.5 GET `/api/status` tecWatch response
| Validation Check | Mechanism | Failure Code | Error Details |
| :--- | :--- | :--- | :--- |
| **Mandatory Fields / Data Types / Allowed Values** | Strict `StatusResponse` model (`src/models/status.py`) | `502 Bad Gateway` | `validation_errors` list |
| **Unexpected Content** | Pydantic `extra = 'forbid'` | `502 Bad Gateway` | `Unexpected field '<field>' is not permitted` |
| **Upstream unreachable / error / timeout** | HTTP client | `502` / `504` | `Cannot connect ...`, `Target server returned error code ...`, `timed out` |

### 6.6 Consistency rules (analysis report)
- Trace message `message_id` values are unique.
- A failure finding's `message_id` (when not `null`) references an existing trace message.
- `expected_length` and `actual_length` are both set or both `null`, and `actual_length` equals the `length` of the referenced trace message.

---

## 7. Error Response Schema

All errors follow a consistent, standardized envelope:

```json
{
  "error": "Validation Error",
  "detail": "The request payload failed validation criteria (check mandatory fields, data types, message length, or unexpected content).",
  "validation_errors": [
    {
      "field": "summary",
      "type": "missing",
      "message": "Mandatory field 'summary' is required but was not provided."
    }
  ]
}
```
