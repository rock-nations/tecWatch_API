# tecWatch – Configurable Status and Post-Analysis API Layer

A configurable API layer for communication between **tecWatch**, **analysis components**, and the **DBLTAS Web GUI**.

## 🌟 Key Features

- **Zero-Code Server Switching**: Point to any remote tecWatch hardware or DBLTAS server simply by editing `config/config.yaml` or setting environment variables.
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
    GUI["DBLTAS Web GUI"] <-->|GET /api/status\nPOST /api/analysis| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    AnalysisComp["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config/config.yaml"] -.->|Dynamic Settings| Gateway
```

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

### 2. POST Analysis Result (`/api/analysis`)

Submits communication trace analysis results. Accepts both JSON and XML.

#### Request (JSON):
```bash
curl -X POST "http://localhost:8000/api/analysis" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "analysis_id": "TRACE-RUN-1001",
    "device_id": "TW-NODE-01",
    "timestamp": "2026-10-03T12:00:00Z",
    "analysis_type": "TRACE_COMMUNICATION",
    "result_status": "FAILED",
    "summary": "Message length error detected on CAN bus packet ID 127.",
    "trace_messages": [
      {
        "timestamp": "2026-10-03T12:00:00Z",
        "sender": "ECU_ENGINE",
        "receiver": "TECWATCH_RECORDER",
        "protocol": "CAN",
        "message_type": "TELEMETRY",
        "status": "FAILED",
        "error_reason": "Message Length Error"
      }
    ],
    "failure_findings": [
      {
        "message_id": "127",
        "expected_length": 64,
        "actual_length": 60,
        "result": "Message Length Error"
      }
    ],
    "data_comparisons": [
      {
        "field": "MessageID",
        "expected": "1001",
        "actual": "1001",
        "result": "OK"
      },
      {
        "field": "Length",
        "expected": "64",
        "actual": "60",
        "result": "Error"
      }
    ]
  }'
```

**Response (JSON)**:
```json
{
  "status": "SUCCESS",
  "message": "Post-analysis result validated and sent to target server",
  "analysis_id": "TRACE-RUN-1001",
  "processed_at": "2026-10-03T12:00:01Z"
}
```

---

### 3. GET Analysis Results (`/api/analysis`) - Web GUI Integration

Used by Akif's Web GUI to display the analysis dashboard, search, filter, and inspect failures.

#### List & Filter:
```bash
# Query all analysis records
curl -s http://localhost:8000/api/analysis

# Filter by outcome status
curl -s "http://localhost:8000/api/analysis?result_status=FAILED"

# Search trace logs
curl -s "http://localhost:8000/api/analysis?search=CAN"
```

#### Detailed View (Failure Findings & Data Comparison):
```bash
curl -s "http://localhost:8000/api/analysis/TRACE-RUN-1001"
```


#### Request (XML):
```bash
curl -X POST "http://localhost:8000/api/analysis" \
  -H "Content-Type: application/xml" \
  -H "Accept: application/xml" \
  -d '<?xml version="1.0" encoding="UTF-8"?>
<AnalysisResult>
  <analysis_id>AN-98432</analysis_id>
  <device_id>TW-10928</device_id>
  <timestamp>2026-10-02T12:05:00Z</timestamp>
  <analysis_type>SPECTRAL_VIBRATION</analysis_type>
  <result_status>PASSED</result_status>
  <metrics>
    <peak_frequency_hz>120.5</peak_frequency_hz>
    <rms_acceleration>0.045</rms_acceleration>
  </metrics>
  <summary>Vibration levels within normal operating tolerances.</summary>
</AnalysisResult>'
```

---

### 3. Dynamic Configuration Inspection & Hot Reload

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

| Validation Test | Status Code | Error Message / Details |
| :--- | :--- | :--- |
| **Payload > Max Size** | `413 Payload Too Large` | `"Request body size exceeds configured limit"` |
| **Missing Mandatory Field** | `422 Unprocessable Entity` | `"Mandatory field '<name>' is required but was not provided"` |
| **Invalid Data Type** | `422 Unprocessable Entity` | `"Invalid data type for field '<name>'"` |
| **Unexpected Content (Extra Keys)** | `422 Unprocessable Entity` | `"Unexpected field '<name>' is not permitted"` |
| **Invalid / Malformed JSON** | `400 Bad Request` | `"Malformed JSON syntax at line X, col Y"` |
| **Invalid / Malformed XML** | `400 Bad Request` | `"Invalid XML syntax or entity error"` |
| **Wrong Content-Type** | `415 Unsupported Media Type`| `"Unsupported Content-Type. Must be application/json or application/xml"` |

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
│   ├── config.yaml          # Target server & API endpoints configuration
│   └── settings.py          # Dynamic configuration loader & Pydantic models
├── src/
│   ├── main.py              # Application entrypoint & ASGI factory
│   ├── api/
│   │   ├── routes.py        # /api/status, /api/analysis, /api/config endpoints
│   │   ├── middleware.py    # Payload size limiter & request logging
│   │   └── error_handlers.py# Standardized JSON/XML error handlers
│   ├── models/
│   │   ├── status.py        # Strict Pydantic models for status
│   │   └── analysis.py      # Strict Pydantic models for post-analysis
│   ├── services/
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
│   └── test_analysis_api.py # Post-analysis unit/integration tests
├── docs/
│   ├── api_documentation.md # Detailed specification document
│   └── examples/            # Sample JSON and XML payloads
├── requirements.txt         # Dependencies
├── pytest.ini               # Pytest configuration
└── README.md                # Documentation and running guide
```
