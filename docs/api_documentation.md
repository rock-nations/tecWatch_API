# tecWatch Configurable Status & Post-Analysis API Documentation

## 1. Overview & Objective

The **tecWatch API** is a high-performance, configurable API layer designed for reliable communication between **tecWatch systems**, **analysis components**, and the **DBLTAS Web GUI**.

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
- **DBLTAS Web GUI Ready**:
  - Pre-configured CORS for browser clients.
  - Interactive Swagger UI at `/docs` and ReDoc at `/redoc`.
  - Comprehensive trace analysis endpoints supporting dashboard listing, search, filtering, and detailed failure-analysis views.

---

## 2. Architecture & Data Flow

```mermaid
flowchart LR
    GUI["DBLTAS Web GUI"] <-->|GET /api/status\nGET /api/analysis\nPOST /api/analysis| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    Analysis["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config.yaml / Env Vars"] -.->|Dynamic Settings| Gateway
```

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

### Live Configuration Reload
You can reload configuration at runtime without restarting the service by issuing:
```http
POST /api/config/reload
```

---

## 4. API Endpoints

### 4.1 GET Status API (`/api/status`)
Retrieves current device telemetry from the configured upstream tecWatch server.

- **URL**: `/api/status`
- **Method**: `GET`
- **Query Parameters**:
  - `device_id` *(optional, string, 1-64 chars)*: Target device identifier.

#### Request Example:
```http
GET /api/status?device_id=TW-10928 HTTP/1.1
Host: localhost:8000
Accept: application/json
```

#### JSON Response (`Accept: application/json`):
```http
HTTP/1.1 200 OK
Content-Type: application/json

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

#### XML Response (`Accept: application/xml`):
```http
HTTP/1.1 200 OK
Content-Type: application/xml

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

### 4.2 POST Analysis Result API (`/api/analysis`)
Accepts trace-analysis results in JSON or XML format. Validates message length, mandatory fields, data types, and rejects unexpected content. Forwards validated data to the target server and stores it for GUI queries.

- **URL**: `/api/analysis`
- **Method**: `POST`
- **Supported Headers**:
  - `Content-Type`: `application/json` or `application/xml`
  - `Accept`: `application/json` or `application/xml`

#### JSON Request Example:
```http
POST /api/analysis HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Accept: application/json

{
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
    },
    {
      "field": "Status",
      "expected": "READY",
      "actual": "READY",
      "result": "OK"
    }
  ]
}
```

#### JSON Response:
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "SUCCESS",
  "message": "Post-analysis result validated and sent to target server",
  "analysis_id": "TRACE-RUN-1001",
  "processed_at": "2026-10-03T12:00:01Z"
}
```

---

### 4.3 GET Analysis Results (`/api/analysis`) - Dashboard View
Allows the DBLTAS Web GUI to list and filter trace-analysis runs.

- **URL**: `/api/analysis`
- **Method**: `GET`
- **Query Parameters**:
  - `result_status` *(optional)*: Filter by outcome (`PASSED`, `FAILED`, `WARNING`).
  - `device_id` *(optional)*: Filter by target device ID.
  - `protocol` *(optional)*: Filter by communication protocol (e.g. `CAN`, `TCP`).
  - `search` *(optional)*: Search keyword inside summaries, error reasons, or analysis IDs.
  - `limit` *(optional, default: 50)*: Number of results to return.

#### Response Example:
```json
[
  {
    "analysis_id": "TRACE-RUN-1001",
    "device_id": "TW-NODE-01",
    "timestamp": "2026-10-03T12:00:00Z",
    "analysis_type": "TRACE_COMMUNICATION",
    "result_status": "FAILED",
    "summary": "Message length error detected on CAN bus packet ID 127.",
    "trace_messages": [ ... ],
    "failure_findings": [ ... ],
    "data_comparisons": [ ... ]
  }
]
```

---

### 4.4 GET Detailed Analysis (`/api/analysis/{analysis_id}`) - Detailed View
Allows the Web GUI to retrieve failure findings, data comparison tables, and full trace message logs for a single analysis run.

- **URL**: `/api/analysis/{analysis_id}`
- **Method**: `GET`

#### Response:
Returns the complete `AnalysisResultRequest` object including `trace_messages`, `failure_findings`, and `data_comparisons`.

---

## 5. Validation Specification

| Validation Check | Mechanism | Failure Code | Error Details |
| :--- | :--- | :--- | :--- |
| **Message Length (Total)** | ASGI middleware checks `Content-Length` | `413 Payload Too Large` | Size in bytes exceeds `max_payload_bytes` |
| **Message Length (Fields)** | Pydantic `min_length` & `max_length` | `422 Unprocessable Entity` | Field value string length out of bounds |
| **Mandatory Fields** | Pydantic required fields | `422 Unprocessable Entity` | `Mandatory field '<field>' is required` |
| **Data Types** | Strict Pydantic types (`StrictInt`, `StrictStr`, etc.) | `422 Unprocessable Entity` | `Invalid data type for field '<field>'` |
| **Message Format** | Content-Type checking | `415 Unsupported Media Type` | Unsupported format (not JSON or XML) |
| **Invalid JSON** | Intercepts `JSONDecodeError` | `400 Bad Request` | `Malformed JSON syntax at line X, col Y` |
| **Invalid XML** | `defusedxml` parser | `400 Bad Request` | `Invalid XML syntax or entity error` |
| **Unexpected Content** | Pydantic `extra = 'forbid'` | `422 Unprocessable Entity` | `Unexpected field '<field>' is not permitted` |

---

## 6. Error Response Schema

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
