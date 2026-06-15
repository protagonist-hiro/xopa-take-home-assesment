# Communication Service API

Asynchronous REST and WebSocket service for call orchestration, state tracking, rate limiting, and post-call recording processing.

## Getting Started

### Prerequisites

- Python 3.10+ (for local setup)
- Redis
- PostgreSQL
- Docker + Docker Compose (for container setup)

### Option 1: Run with Docker

```powershell
docker compose up --build
```

Service endpoints:

- API: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- Debug UI (if enabled): `http://localhost:8000/debug?key=<ADMIN_KEY>`

### Option 2: Local Production-Style Setup (No Docker)

Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Run API + worker:

```powershell
python run_local.py --port 8090
```

Service endpoints:

- API: `http://localhost:8090`
- OpenAPI docs: `http://localhost:8090/docs`
- Debug UI (if enabled): `http://localhost:8090/debug?key=<ADMIN_KEY>`

### First API Calls

Create call:

```bash
curl -X POST http://localhost:8090/calls \
  -H "Authorization: Bearer test-key-1" \
  -H "Content-Type: application/json" \
  -d '{"from":"+15550001111","to":"+15559998888","metadata":{"campaign":"outbound-a"}}'
```

Get call:

```bash
curl -X GET http://localhost:8090/calls/<call_id> \
  -H "Authorization: Bearer test-key-1"
```

Get metrics:

```bash
curl -X GET http://localhost:8090/metrics \
  -H "Authorization: Bearer test-key-1"
```

### Integration Flow

1. Obtain API key from your internal provisioning channel.
2. Create call with `POST /calls`.
3. Subscribe to returned `websocket_url`.
4. Read final state and recording URL via `GET /calls/{call_id}`.
5. Use `GET /metrics` for service-level observability.

## Architecture

- FastAPI for REST and WebSocket endpoints
- Redis for live call state and rate-limit counters
- PostgreSQL for durable call records
- ARQ worker for asynchronous recording processing
- Local or S3-compatible object storage for recording artifacts

## Core Behavior

- `POST /calls` creates a call and starts asynchronous progression
- Per API key enforcement:
  - Concurrent active call limit
  - Calls-per-second (CPS) limit
- Call state path is randomized:
  - `queued -> ringing -> answered -> completed`
  - `queued -> ringing -> unanswered -> completed`
- `WS /ws/{call_id}` streams state transitions in real time
- `GET /calls/{call_id}` returns current state, history, and recording URL
- `GET /metrics` returns active calls, totals, CPS counters, and pending uploads

## Authentication

All HTTP endpoints require:

`Authorization: Bearer <API_KEY>`

API keys are expected to be provisioned through external channels.

## API Contract

### POST /calls

Request:

```json
{
  "from": "+15550001111",
  "to": "+15559998888",
  "metadata": {
    "campaign": "outbound-a"
  }
}
```

Response `201`:

```json
{
  "call_id": "uuid",
  "status": "queued",
  "from_number": "+15550001111",
  "to_number": "+15559998888",
  "websocket_url": "ws://host/ws/<call_id>",
  "created_at": "2026-06-15T12:00:00Z"
}
```

Rate-limit response `429`:

```json
{"error":"Rate limit exceeded"}
```

### GET /calls/{call_id}

Returns call status, state history, and recording URL (when available).

### GET /metrics

Returns:

- `active_calls`
- `total_calls`
- `completed_calls`
- `pending_uploads`
- `cps_current`

Response format is Prometheus exposition text (`text/plain; version=0.0.4`) with service and per-key metrics.

### WS /ws/{call_id}

Emits:

- `current_state`
- `state_change`
- `ping`

## Project Structure

```text
app/
  main.py
  config.py
  auth.py
  rate_limit.py
  call_machine.py
  worker.py
  database.py
  models.py
  redis_client.py
  ws_manager.py
  routers/
    calls.py
    metrics.py
    debug_ui.py
debug.html
run_local.py
requirements.txt
.env
```

## Configuration

Primary environment variables:

- `VALID_API_KEYS`
- `MAX_CONCURRENT_CALLS_PER_KEY`
- `MAX_CPS_PER_KEY`
- `CPS_WINDOW_SECONDS`
- `DATABASE_URL`
- `REDIS_URL`
- `STORAGE_BACKEND` (`local` or `s3`)
- `LOCAL_RECORDINGS_DIR`
- `PUBLIC_BASE_URL`
- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION`
- `DEBUG`
- `ADMIN_KEY`

## API Keys and Limits

API keys and limit overrides are stored in the database table `api_key_configs`.

Behavior:

- Default configured test keys are seeded on startup.
- If a key has no explicit override row values, global defaults are applied.
- If a key row defines limit values, those values are used for that key.

Fields:

- `api_key`
- `is_active`
- `max_concurrent_calls`
- `max_cps`
- `cps_window_seconds`

## Operational Hardening Checklist

- Store all credentials and API keys in a secret manager
- Enforce TLS for REST and WebSocket traffic
- Use strict CORS policy per environment
- Add DB schema migrations (Alembic)
- Export metrics/traces (Prometheus + OpenTelemetry)
- Replace in-process websocket fanout with distributed pub/sub for horizontal scale
- Add dead-letter strategy and retries for background jobs
- Add unit, integration, and load testing in CI

