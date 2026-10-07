# tecWatch – Configurable Status and Post-Analysis API Layer

A configurable API layer for communication between **tecWatch**, **analysis components**, and the **DBLTAS Web GUI**.

## 🌟 Key Features

- **Zero-Code Server Switching**: Point to any remote tecWatch hardware or DBLTAS server simply by editing `config/config.yaml` or setting environment variables.
- **Validated Analysis Report Serving**: `GET /api/analysis` reads the configured analysis report JSON file on every request, validates it, and returns it unchanged to the Web GUI.
- **Dual Payload Formats (JSON & XML)**: Seamlessly accepts and generates both JSON (`application/json`) and XML (`application/xml`).
- **Comprehensive Multi-Tier Validation**:
  - **Message Length**: Enforces request size limits via ASGI middleware (`413 Payload Too Large`) and field length bounds.
  - **Mandatory Fields**: Strict requirement validation (`422 Unprocessable Entity`).
  - **Data Types**: Enforces strict typing without unwanted type coercion.
  - **Message Format**: Validates content type and structural schemas.
  - **Malformed Syntax Protection**: Safely catches invalid JSON or malformed XML (`400 Bad Request`).
  - **Unexpected Content**: Automatically rejects unauthorized/extra payload keys (`extra='forbid'`).
- **DBLTAS Web GUI Ready**: Includes CORS headers, OpenAPI / Swagger documentation (`/docs`), and ReDoc (`/redoc`).
- **Dynamic Configuration Reloading**: Reload target servers on the fly without restarting the process (`POST /api/config/reload`).
- **Built-in Mock Simulator**: Ready-to-use mock server for testing and local development.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    GUI["DBLTAS Web GUI"] -->|GET /api/status\nGET /api/analysis| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    Report[("Analysis report JSON\n(analysis.report_path)")] -->|read + validate\non every GET| Gateway
    AnalysisComp["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured tecWatch / Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config/config.yaml"] -.->|Dynamic Settings| Gateway
```

On initial load the Web GUI calls `GET /api/status` (proxied to the configured tecWatch server) and `GET /api/analysis` (read from the analysis report file). The GUI never posts analysis data; `POST /api/analysis` is for analysis components and forwards validated results to the configured target server.

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

analysis:
  report_path: "data/data-analysis-report.json"  # Report served by GET /api/analysis
  max_report_bytes: 1048576                       # 1 MB maximum report length

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

> **Analysis Report File**:
> A relative `analysis.report_path` is resolved against the backend folder; absolute paths work too. To serve another report, change the path in `config/config.yaml` (then `POST /api/config/reload`) or set:
> ```bash
> export TECWATCH_ANALYSIS_REPORT_PATH="/path/to/data-analysis-report.json"
> ```
> The file is read on every request, so a regenerated report is served without restarting the API.

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

#### Request (JSON):
```bash
curl -X GET "http://localhost:8000/api/status?device_id=TW-10928" \
  -H "Accept: application/json"
```

**Response (JSON)**:
```json
{
  "device_id": "TW-10928",
  "status": "OPERATIONAL",
  "battery_level": 94.5,
  "uptime_seconds": 36000,
  "temperature": 28.4,
  "timestamp": "2026-10-02T12:00:00Z",
  "active_alerts": []
}
```

#### Request (XML):
```bash
curl -X GET "http://localhost:8000/api/status?device_id=TW-10928" \
  -H "Accept: application/xml"
```

**Response (XML)**:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<tecWatchStatus>
  <device_id>TW-10928</device_id>
  <status>OPERATIONAL</status>
  <battery_level>94.5</battery_level>
  <uptime_seconds>36000</uptime_seconds>
  <temperature>28.4</temperature>
  <timestamp>2026-10-02T12:00:00Z</timestamp>
</tecWatchStatus>
```

---

### 2. GET Analysis Report (`/api/analysis`) - Web GUI Integration

Called by the DBLTAS Web GUI on initial load. The API reads the configured analysis report file, validates it, and returns it unchanged (format: [`data/data-analysis-report.json`](data/data-analysis-report.json)).

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

### 3. POST Analysis Result (`/api/analysis`)

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

### 4. Dynamic Configuration Inspection & Hot Reload

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

---

## 📂 Project Structure

```text
tecwatch_api/
├── config/
│   ├── config.yaml          # Target server, API endpoints & analysis report configuration
│   └── settings.py          # Dynamic configuration loader & Pydantic models
├── data/
│   └── data-analysis-report.json # Analysis report served by GET /api/analysis
├── src/
│   ├── main.py              # Application entrypoint & ASGI factory
│   ├── api/
│   │   ├── routes.py        # /api/status, /api/analysis, /api/config endpoints
│   │   ├── middleware.py    # Payload size limiter & request logging
│   │   └── error_handlers.py# Standardized JSON/XML error handlers
│   ├── models/
│   │   ├── status.py        # Strict Pydantic models for status
│   │   └── analysis.py      # Strict Pydantic models for the analysis report
│   ├── services/
│   │   ├── analysis_report.py # Reads & validates the analysis report file
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
│   └── test_analysis_api.py # Analysis report (GET) & post-analysis (POST) tests
├── docs/
│   ├── api_documentation.md # Detailed specification document
│   └── examples/            # Sample JSON and XML payloads
├── requirements.txt         # Dependencies
├── pytest.ini               # Pytest configuration
└── README.md                # Documentation and running guide
```
