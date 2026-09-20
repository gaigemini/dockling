# Docling Document Processing API

Production-ready FastAPI service for document conversion and chunking with [Docling](https://github.com/docling-project/docling) — extracts text and tables from PDF, DOCX, PPTX, XLSX, HTML, CSV, Markdown, and images.

Key capabilities:

- **Sync & async processing** — direct endpoints for quick jobs; a Redis-backed queue with submit-and-poll plus webhook callbacks for long-running jobs (30–90+ minutes)
- **Reliable queueing** — atomic `BLMOVE` in-flight tracking, a janitor watchdog for stalled tasks, queue/processing timeouts, and graceful cancellation
- **Object storage (MinIO / S3-compatible)** — uploaded inputs and result artifacts; results retained **7 days** (Redis TTL and bucket lifecycle rule aligned); local-disk fallback for development
- **Resumable uploads** — chunked upload sessions (Redis-backed, bound to the authenticated user) for large files
- **Production hardening** — fail-closed config loader, `ApiResponse` envelope for all errors, correlation-ID logging, SSO token introspection with short-lived cache, HMAC-signed webhooks, CORS guard, and a conversion concurrency limiter

## Architecture

```
Client → API (FastAPI) → Redis (task:queue / task:processing / task:{id} status)
                       → Task Worker (Docling on thread pool + janitor)
                       → MinIO (uploads/ inputs, results/ artifacts)
```

- **API** — validates requests, stores uploads, submits tasks, serves status/results
- **Worker** — BLMOVE dequeue, soft processing timeout, result upload to MinIO, webhook dispatch
- **Janitor** — recovers stranded tasks, expires stale queue entries, sweeps temp files and dangling artifacts

## Requirements

- Python 3.10+ (3.12 recommended)
- Redis 7+
- MinIO (S3-compatible) — optional in dev (`MINIO_ENABLED=false` uses a local fallback under `TEMP_DIR/storage`)
- Docker + Docker Compose (optional)
- NVIDIA GPU (optional) for accelerated inference

## Getting started (local)

```bash
mkdir gai && cd gai
python3 -m venv .
source bin/activate

pip install -r requirements.txt          # production dependencies
pip install -r requirements-dev.txt      # pytest and dev tooling

# Environment: copy the templates (real env files are git-ignored)
cp env/dev.env.example env/dev.env       # edit values as needed
echo "APP_ENV=dev" > .env

# Infrastructure (optional: Redis/MinIO via Docker)
docker network create dbr0 2>/dev/null || true
docker compose up -d redis minio

# Run the API
uvicorn app.main:app --reload --port 8000
```

- Interactive docs: http://localhost:8000/docs (DEBUG mode only)
- Health (aggregated): http://localhost:8000/health → `200` healthy, `503` with per-component status otherwise

### Docker Compose (full stack)

```bash
docker network create dbr0   # compose expects this external network
docker compose up -d --build
```

Services: `redis` (6379), `minio` (API 9000, console 9001), `docling-api` (port 8000 exposed internally — put it behind your reverse proxy).

## Configuration

Settings load in this order: `.env` selects `APP_ENV` (default `dev`) → `env/{APP_ENV}.env` overrides the defaults defined in `config/base.py`.

> The loader **fails closed**: a broken or missing prod env file (or `DEBUG=true` in prod) aborts startup instead of falling back to dev defaults.

Templates: `env/dev.env.example`, `env/prod.env.example`, `env/test.env.example`. Real `env/*.env` files are git-ignored — never commit secrets.

| Setting | Default | Description |
|---|---|---|
| `TEMP_DIR` | `uploads/tmp` | Local scratch (pending uploads, MinIO downloads, storage fallback) |
| `MINIO_ENABLED` | `false` | `true` → MinIO/S3; `false` → local-disk fallback |
| `MINIO_ENDPOINT` / `MINIO_BUCKET` | `localhost:9000` / `docling` | Object storage target |
| `MINIO_DELETE_INPUT_ON_COMPLETE` | `true` | Delete the input object after processing (else kept for `MINIO_RETENTION_HOURS`) |
| `MINIO_RESULT_TTL_DAYS` | `7` | Lifecycle expiry (days) for the `results/` prefix |
| `TASK_RESULT_TTL` | `604800` (7d) | Redis TTL for terminal task entries (aligned with MinIO) |
| `TASK_QUEUE_TIMEOUT` | `43200` (12h) | Max queue wait before a task becomes `expired` |
| `TASK_PROCESSING_TIMEOUT` | `5400` (90m) | Default max processing time before `timeout` |
| `TASK_PROCESSING_TIMEOUT_MAX` | `10800` (3h) | Cap for the per-request `timeout_seconds` override |
| `UPLOAD_SESSION_TTL` | `7200` (2h) | Resumable upload session TTL |
| `JANITOR_INTERVAL` / `WORKER_CONCURRENCY` | `60` / `1` | Watchdog interval (s) and worker concurrency (GPU-bound) |
| `CALLBACK_TIMEOUT` / `CALLBACK_MAX_RETRIES` / `CALLBACK_ALLOWED_HOSTS` | `10.0` / `3` / empty | Webhook delivery: retries, timeout, optional host allowlist (private/loopback IPs blocked) |
| `MAX_CONCURRENT_CONVERSIONS` | `4` | Sync endpoint limiter (`429` when saturated) |
| `AUTH_INTROSPECT_CACHE_TTL` | `60` | Token introspection cache in seconds |
| `SECRET_KEY` | — | HMAC key for webhook signatures (rotate in prod) |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue + task state backend |

## API overview

All API responses use the `ApiResponse` envelope (`status: 0` success / `4` error). Authentication: Bearer token validated via SSO introspection (bypass with `DISABLE_AUTH=true` in dev/test).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/convert` | Convert a document (stream or file-based) |
| `POST` | `/api/v1/convert_n_chunk` | Convert + chunk (for LLM/RAG) |
| `POST` | `/api/v1/convert_text` / `/chunk_text` | Convert/chunk raw text (JSON body, no file) |
| `POST` | `/api/v1/convert_async` / `/convert_n_chunk_async` | Submit an async task (`202`) — supports `callback_url`, `timeout_seconds` |
| `GET` | `/api/v1/tasks/{task_id}` | Poll status: timestamps, deadlines, `result_summary`, presigned `result_url`, `poll_after` |
| `GET` | `/api/v1/tasks/{task_id}/result` | Fetch the result artifact (404/409/410 semantics, 7-day retention) |
| `DELETE` | `/api/v1/tasks/{task_id}` | Cancel a task while it is still `pending` |
| `GET` | `/api/v1/tasks` | List recent tasks |
| `POST` | `/api/v1/upload/init` | Start a resumable upload session |
| `PUT` | `/api/v1/upload/{upload_id}` | Upload or resume a chunk (`Content-Range` supported) |
| `GET` | `/api/v1/upload/{upload_id}` | Upload session status/progress |
| `GET` | `/health` | Aggregated health: converter, Redis, storage, worker |

### Async task lifecycle

```
pending → processing → completed
                     → failed
                     → timeout      (processing deadline exceeded)
pending → cancelled
pending → expired                  (waited > TASK_QUEUE_TIMEOUT in the queue)
```

**Results are not returned inline.** Converted markdown/chunks (with embedded images) can reach tens of MB, so every completed task is uploaded to `results/{task_id}/result.json` in MinIO. Redis stores only status, `result_summary`, and `result_ref` — both sides expire after 7 days. Fetch the artifact via the presigned `result_url` or `GET /api/v1/tasks/{task_id}/result`.

**Webhook callbacks.** Pass `callback_url` when submitting; the service POSTs a compact JSON payload on terminal status with headers `X-Task-Id` and `X-Signature: sha256=<HMAC-SHA256(body, SECRET_KEY)>`. Delivery retries up to `CALLBACK_MAX_RETRIES` with exponential backoff — treat deliveries as at-least-once (idempotency key: `task_id`). Polling remains the fallback channel.

**Timeout semantics.** Processing timeouts are soft: Docling runs on a pre-warmed in-process (GPU) thread pool that cannot be hard-killed — the task status is guaranteed to transition (`timeout`), while the stale thread finishes in the background. The janitor also recovers tasks whose worker crashed mid-processing.

Full request/response examples: see [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) (Bahasa Indonesia) and `test.rest` (REST client collection).

## Testing

```bash
./bin/python -m pytest    # or: pytest (pythonpath=. is configured in pytest.ini)
```

- Unit tests (`tests/unit/`) mock Redis, MinIO, and HTTP — no external services required
- API tests (`tests/api/`) run against the ASGI app with an in-memory storage double
- Coverage includes task lifecycle, janitor transitions, timeouts, resumable-upload offsets, webhook retries, storage fallback, and the fail-closed config loader

## Project structure

```
app/
├── endpoints/        # API routes (sync, async task, resumable upload)
├── services/         # conversion, task, file, storage (MinIO), callback services
├── workers/          # TaskWorker: consumer loop + janitor watchdog
├── models/           # Pydantic request/response and task models
├── dependencies/     # auth (SSO introspection + cache), logger
├── utils/            # redis client, http client, params, errors
├── main.py           # app entry point, lifespan, exception handlers
└── middleware.py     # correlation ID + logging middleware
config/               # settings package (fail-closed loader)
env/                  # env files (git-ignored) + .example templates
tests/                # unit + api test suites
docs/                 # API documentation
```

## Security notes

- `env/*.env` files are git-ignored; only `.example` templates are committed. If secrets were previously committed, **rotate** `SECRET_KEY`, `jwt_secret_key`, and `SSO_CLIENT_SECRET`.
- Webhook targets are validated (absolute `http(s)` URLs; private/loopback addresses blocked unless allowlisted via `CALLBACK_ALLOWED_HOSTS`).
- CORS: avoid `*` combined with credentials in production — set explicit `CORS_ORIGINS`.
- Internal error details are logged server-side and never returned to clients.
