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
  - Validated analysis report endpoint providing trace messages, failure findings, and data comparisons for the dashboard.

---

## 2. Architecture & Data Flow

```mermaid
flowchart LR
    GUI["DBLTAS Web GUI"] -->|GET /api/status\nGET /api/analysis| Gateway["tecWatch API Layer\n(FastAPI Gateway)"]
    Report[("Analysis report JSON\n(analysis.report_path)")] -->|read + validate\non every GET| Gateway
    Analysis["Analysis Components"] -->|POST /api/analysis\n(JSON or XML)| Gateway
    Gateway <-->|Dynamic Upstream\nhttp://host:port| Server["Configured tecWatch / Target Server\n(e.g., 192.168.1.10:8080)"]
    Config["config.yaml / Env Vars"] -.->|Dynamic Settings| Gateway
```

1. On initial load the Web GUI calls `GET /api/status` and `GET /api/analysis`.
2. `GET /api/status` is proxied to the configured tecWatch server and validated.
3. `GET /api/analysis` reads the configured analysis report file (produced by the data-analysis component), validates it, and returns it unchanged.
4. Analysis components may submit results with `POST /api/analysis`; they are validated and forwarded to the configured target server. The Web GUI never posts analysis data.

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
  report_path: "data/data-analysis-report.json"  # Report served by GET /api/analysis (relative to the backend folder)
  max_report_bytes: 1048576                       # 1 MB maximum report length

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

### 4.2 GET Analysis Report API (`/api/analysis`)
Called by the DBLTAS Web GUI on initial load. Reads the configured analysis report file (`analysis.report_path`), validates it (message length, message format, mandatory fields, data types, unexpected content, consistency) and returns it **unchanged**. The file is read on every request, so a regenerated report is served without restarting the API.

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
| **Consistency** | Model validators (see 6.3) | `422 Unprocessable Entity` | e.g. `message_id 'x' does not match any trace message` |

### 6.2 GET `/api/analysis` report file
| Validation Check | Mechanism | Failure Code | Error Details |
| :--- | :--- | :--- | :--- |
| **File Exists** | File read | `404 Not Found` | `Analysis report file '<name>' does not exist.` |
| **Message Length (Total)** | At most `max_report_bytes` are read | `500 Internal Server Error` | `Analysis report exceeds the configured size limit (N bytes).` |
| **Message Format** | UTF-8 JSON object | `500 Internal Server Error` | `Malformed JSON syntax at line X, column Y`, `must be a JSON object` |
| **Schema** (lengths, mandatory fields, data types, unexpected content, consistency) | Same model as POST | `500 Internal Server Error` | `validation_errors` list as in section 7 |

### 6.3 Consistency rules
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
