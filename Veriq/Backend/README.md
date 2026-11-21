# VeriQ

VeriQ is a developer platform for testing the correctness of Celery background jobs under
controlled execution failures. It will eventually let developers register a Python application,
configure experiments against real background tasks, inject controlled worker failures, observe task
execution / worker recovery / message redelivery, verify business invariants against the application's
own PostgreSQL database, and inspect experiment timelines through a web dashboard.

The product was called QueueProof when this repository's backend/frontend foundation was built; the
Python SDK, the package name and the docs now say **VeriQ**. Internal identifiers that were already
shipped (the Compose project/DB name `queueproof`, the `queueproof_pgdata` volume) keep their original
names so existing environments are not broken.

**This repository now covers discovery, ordinary task observation, reliability-test planning and
supervised execution of approved test cases.** The SDK instruments Celery automatically, VeriQ
stores registered tasks, worker instances, queues, execution attempts and their event timelines,
and the dashboard exposes a task catalog with per-task observation controls. On top of that, the
backend can discover checkpoints, store versioned Task Test Contracts, register infrastructure
adapters, evaluate scenario compatibility, generate a reproducible scenario matrix, track a
test-plan review/approval lifecycle, and then execute one approved case in an isolated environment
with a controlled fault, observed recovery and a deterministic verdict.

Approval still executes nothing: a run starts only through the explicit start endpoint. The SDK only
observes; it never starts, pauses or crashes a worker. The runner provisions the environment, injects
the fault through the supervisor and evaluates recorded evidence — never an LLM, never a business
effect. See [`docs/reliability-planning.md`](docs/reliability-planning.md) for the planning model and
[`docs/reliability-runtime.md`](docs/reliability-runtime.md) for execution, fault injection, recovery
and verdicts.

## Architecture (initial platform)

```text
Browser (React + TS + Vite, :5173)
    │  HTTP /api/v1/*  (Vite dev proxy, or VITE_API_URL)
    ▼
FastAPI backend (Uvicorn, :8000)
    │  routes (thin) → services (business rules / transactions) → SQLAlchemy 2.0 sync ORM
    ▼
PostgreSQL 16 (:5432, Docker volume queueproof_pgdata)
    ▲
    │  X-API-Key: /api/v1/task-executions/events, /workers/events, /tasks/discovery
    │            /api/v1/experiment-runs/{id}/events (existing experiment path)
    │
VeriQ SDK (`veriq`, installed in the target app)
    │  Celery signals: task_prerun/postrun/failure/retry, worker_ready/heartbeat/shutdown
▼
Target application's Celery workers (normal queue + isolated `veriq.test` worker)
```

The components are the **backend** (control API, metadata DB, experiments/runs/events), the
**SDK** (`sdk/`, a transport that a target app installs), the **runner** (planned: coordinates
experiments and controls authorized Docker workers), and the **target application** (external app
with Celery, Redis and its own PostgreSQL). The SDK never controls Docker or processes; that stays a
runner responsibility.

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (sync), Pydantic v2, pydantic-settings,
  psycopg (psycopg3), Alembic.
- **Frontend:** React 18, TypeScript, Vite 6. State-based navigation; no router dependency.
- **Infra:** Docker Compose (development only). No Redis/Celery/queues.
- **Migrations:** Alembic. Migrations are **not** run automatically on API startup; run them explicitly.

### Repository structure

```text
queueproof/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + CORS
│   │   ├── core/config.py           # Pydantic Settings (DATABASE_URL, APP_ENV, CORS_ORIGINS)
│   │   ├── core/database.py         # Engine, SessionLocal, get_db dependency
│   │   ├── models/                  # SQLAlchemy 2.0 models: experiments, runs, events,
│   │   │                            #   registered_tasks, workers, worker_queues,
│   │   │                            #   task_executions, execution_events
│   │   ├── schemas/                 # Pydantic v2 request/response models
│   │   ├── domain/                  # pure rules: adapter catalogue, scenario catalogue,
│   │   │                            #   compatibility engine, matrix generation, recovery
│   │   │                            #   policy/evaluator and the run state machine
│   │   ├── runtime/                 # environment provisioning, worker supervisor, execution
│   │   │                            #   controller, fault injectors, observer, evaluator,
│   │   │                            #   finalizer, orchestrator and background scheduler
│   │   ├── api/router.py            # /api/v1 router assembly
│   │   ├── api/routes/              # health, applications, experiments, runs,
│   │   │                            #   observations (SDK ingest), catalog (dashboard),
│   │   │                            #   planning (contracts, adapters, matrix, plans)
│   │   └── services/                # application, experiment, run, discovery, observation,
│   │                                #   checkpoint, contract, adapter, compatibility,
│   │                                #   matrix, test-plan
│   ├── alembic/                     # env.py (reads DATABASE_URL), versions/0001..0005
│   ├── scripts/wait_for_database.py # blocks until Postgres accepts connections
│   ├── scripts/runtime_e2e.py       # end-to-end run against real Docker + real worker
│   ├── tests/                       # pytest suite (isolated SQLite, see Testing)
│   ├── alembic.ini
│   ├── requirements.txt / requirements-dev.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/                     # typed client + TS response types
│   │   ├── hooks/useAsync.ts        # loading / error / reload state
│   │   ├── components/ui.tsx        # Loading, ErrorState, EmptyState, Badge
│   │   └── pages/                   # TaskCatalog, TaskDetail, Workers, Applications
│   ├── index.html  ├── vite.config.ts  ├── tsconfig*.json  └── package.json
├── sdk/                             # independently installable `veriq` Python package
│   ├── pyproject.toml  ├── README.md
│   ├── src/veriq/                   # client, config, events, exceptions, transport/http,
│   │                                #   context (contextvars), celery (signal integration)
│   └── tests/
├── examples/celery-target-app/      # reference isolated-worker Compose integration
│   ├── app/                         # celery_app.py, tasks.py, veriq_setup.py,
│   │                                #   worker.py (integration entrypoint), main.py (FastAPI)
│   ├── compose.yaml                 # redis, api, worker, veriq-worker
│   ├── Dockerfile  ├── requirements.txt  ├── .env.example  └── README.md
├── docker-compose.yml               # DEVELOPMENT ONLY
├── .env.example
├── .gitignore
└── README.md
```

## Database schema

All tables use UUID primary keys and timezone-aware timestamps. Relationships are 1:N chains:

```text
target_apps ──1:N──► experiments ──1:N──► experiment_runs ──1:N──► experiment_events
```

| Table | Key fields / constraints |
|---|---|
| `target_apps` | `id` UUID PK; `name` VARCHAR(150) UNIQUE, non-empty; `description` TEXT NULL; `environment` VARCHAR(30) (`development`/`test`); `api_key_hash` CHAR(64) UNIQUE NULL (SHA-256 of the SDK key — never the plaintext); `created_at`, `updated_at` TIMESTAMPTZ. No other credentials stored. |
| `experiments` | `id` UUID PK; `target_app_id` FK → `target_apps` (ON DELETE RESTRICT); `name` VARCHAR(200), `task_name` VARCHAR(255), `scenario` VARCHAR(100) (`crash_after_commit`), `checkpoint_name` VARCHAR(150) NULL, `timeout_seconds` INT CHECK 1–3600 default 60, `status` VARCHAR(30) default `DRAFT`, `config_snapshot` JSONB NULL, timestamps. Index on `target_app_id`. |
| `experiment_runs` | `id` UUID PK; `experiment_id` FK → `experiments` (RESTRICT); `run_number` INT > 0, UNIQUE per experiment; `status` CHECK (`PENDING, PREPARING, RUNNING, VERIFYING, COMPLETED, FAILED, ERROR, INCONCLUSIVE, CANCELLED`) default `PENDING`; `verdict` CHECK NULL or (`PASSED, FAILED, INCONCLUSIVE`); `operation_id` UUID NULL; `config_snapshot` JSONB NOT NULL (immutable per-run snapshot); `error_message` TEXT NULL; `created_at`, `started_at`, `finished_at` TIMESTAMPTZ. |
| `experiment_events` | Append-only. `id` UUID PK; `experiment_run_id` FK → `experiment_runs` (RESTRICT); `event_type` VARCHAR(100); `source` CHECK (`API, RUNNER, SDK, OBSERVER, INVARIANT_CHECKER`); `payload` JSONB NULL; `occurred_at` TIMESTAMPTZ NOT NULL (event time, not arrival order); `client_event_id` UUID NULL (SDK idempotency key, UNIQUE per run). Composite index `(experiment_run_id, occurred_at)`. |
| `registered_tasks` | `id` UUID PK; `target_app_id` FK (CASCADE); `task_name` VARCHAR(255); `status` CHECK (`DISCOVERED, OBSERVING, DISABLED`); `discovery_source`; `first_seen_at`, `last_seen_at`, `discovered_at`; `task_metadata` JSONB NULL. UNIQUE `(target_app_id, task_name)`, index `(target_app_id, status)`. No task code or arguments are stored. |
| `workers` | `id` UUID PK; `target_app_id` FK (CASCADE); `worker_instance_id` VARCHAR(64) (one process lifetime); `hostname`, `worker_hostname`, `pid`, `process_start_identity`; `status` CHECK (`ONLINE, OFFLINE, UNKNOWN`); `registered_task_names` JSONB; `first_seen_at`, `last_seen_at`. UNIQUE `(target_app_id, worker_instance_id)`, index `(target_app_id, status)`. Rows are never deleted on shutdown. |
| `worker_queues` | `id` UUID PK; `worker_id` FK (CASCADE); `queue_name`; `exchange`, `routing_key`; `is_configured` vs `is_consumed`; `first_seen_at`, `last_seen_at`. UNIQUE `(worker_id, queue_name)`. |
| `task_executions` | One row per actual attempt. `id` UUID PK; `target_app_id` FK; `registered_task_id` FK NULL (SET NULL); `execution_id` UUID UNIQUE; `celery_task_id` VARCHAR(255) (may repeat across attempts); `task_name`, `worker_id` FK NULL, `worker_instance_id`, `worker_hostname`, `pid`, `process_start_identity`, `queue_name`; `experiment_run_id` FK NULL (SET NULL, optional link); `veriq_operation_id`; `status` CHECK (`RUNNING, SUCCEEDED, FAILED, RETRYING`); `started_at`, `finished_at`, `duration_ms`. Indexes on `(target_app_id, started_at)`, `(target_app_id, task_name)`, `celery_task_id`, `experiment_run_id`. |
| `execution_events` | Append-only timeline per execution. `id` UUID PK; `task_execution_id` FK (RESTRICT); `event_type` VARCHAR(100); `source` CHECK (`SDK, BACKEND, OBSERVER`); `payload` JSONB NULL; `occurred_at`; `client_event_id` UUID NULL (UNIQUE per execution). Index `(task_execution_id, occurred_at)`. |

Business rules enforced in services/schemas: an application cannot be deleted while experiments
reference it; only `DRAFT` experiments can be edited or deleted; an experiment cannot reference a
nonexistent application (HTTP 422); timeout must be positive and ≤ 3600; run `status` and `verdict`
are separate concepts (a failed execution status does not by itself mean the invariant failed).
There is no update path for events: a new fact is a new row.

Ordinary telemetry never writes `experiment_events` and never needs a fake run. Executions link to an
`experiment_runs` row only when the SDK reports VeriQ headers and the run belongs to the authenticated
application. `registered_tasks` are discovered from the Celery app independently of whether their
telemetry is enabled.

## Reliability-test planning

Planning tables are additive (`alembic` revision `0004_planning`). The conceptual flow is:

```text
registered_tasks ──► task_checkpoints (discovered from SDK checkpoint events)
        │
        ├──► task_test_contracts (+ immutable versions: safe input, effect measurement,
        │                                             assertions, cleanup)
        ├──► application_adapters (http / database / broker / storage / custom)
        ├──► task_scenario_selections + checkpoint_scenario_selections
        │
        ▼
  compatibility engine (COMPATIBLE / NEEDS_CONFIGURATION / UNSUPPORTED, with reasons)
        ▼
  test_plans ──1:N──► test_plan_revisions ──1:N──► test_plan_test_cases
                                (DRAFT → VALIDATING → READY_FOR_REVIEW → APPROVED)
```

* Normal execution telemetry is untouched: checkpoints remain report-only, and an execution can
  succeed while an experiment or plan fails.
* `app/domain/` is pure Python (no ORM, no FastAPI), so compatibility evaluation and matrix
  generation are deterministic and unit-testable.
* Approval records `approved_revision`; any later plan or contract change requires review again.
* No part of this stage executes tasks, injects failures or controls workers.

API groups live under `/api/v1`: `/scenarios`, `/adapter-types`,
`/applications/{id}/adapters`, `/applications/{id}/contracts`,
`/applications/{id}/checkpoints`, `/applications/{id}/registered-tasks/{task}/scenarios`,
`/applications/{id}/compatibility/evaluate` and `/applications/{id}/test-plans`. The
[planning documentation](docs/reliability-planning.md) lists the contract schema, adapter
capabilities, scenario requirements, compatibility reason codes and the approval lifecycle.

## Prerequisites

- Docker + Docker Compose (recommended path), **or** Python 3.12+ and Node 22+ for local runs.
- You will supply all secrets yourself — no credentials are committed.

## Environment setup

```bash
cp .env.example .env          # fill in POSTGRES_PASSWORD and other values
cp backend/.env.example backend/.env   # only needed for non-Compose backend runs
cp frontend/.env.example frontend/.env # only if you set VITE_API_URL
```

Variables you must fill in:

| Variable | Where | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | root `.env` | PostgreSQL password (Compose) |
| `DATABASE_URL` | `backend/.env` / environment | SQLAlchemy URL, e.g. `postgresql+psycopg://queueproof:<pw>@localhost:5432/queueproof`. Required — the backend fails with a clear Pydantic validation error if missing. Plain `postgresql://` URLs are normalized to the psycopg driver. |
| `APP_ENV` | backend | `development` (default), `test`, or `production` |
| `CORS_ORIGINS` | backend | Comma-separated origins, default `http://localhost:5173` |
| `VITE_API_URL` | frontend | Backend base URL; leave empty for the dev proxy |

Defaults for `POSTGRES_DB`, `POSTGRES_USER`, and ports can stay as-is for local development.

## Docker Compose startup (development only)

```bash
cp .env.example .env   # set DATABASE_URL for the backend
cp backend/.env.example backend/.env
docker compose up --build
```

The root compose file in this checkout runs the backend container and reads `DATABASE_URL` from the
environment (for example a managed PostgreSQL URL) rather than starting a local `db` service. It
waits for database readiness via `scripts/wait_for_database.py`. **This is a non-production
development setup** — it runs uvicorn, not a production build. Run the dashboard separately with
`cd frontend && npm install && npm run dev` (see below).

Then, in a second terminal, run migrations explicitly:

```bash
docker compose exec backend alembic upgrade head
```

Verify:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","database":"connected"}
# Start the dashboard: cd frontend && npm run dev  ->  http://localhost:5173
```

Stop with `docker compose down` (add `-v` to also delete any local database volume).

## Database migrations

Migrations live in `backend/alembic/versions/`. Current head: `0005_runtime`
(`0005` adds the runner tables — test case runs, environments, workers, fault events, recovery
observations, runtime events, checkpoint waits and run credentials — plus additive
`target_apps.runtime_config` and `test_plan_test_cases.recovery_policy`; `0004` adds planning;
`0003` adds discovery + ordinary execution; `0002` adds `target_apps.api_key_hash` and
`experiment_events.client_event_id`; `0001_initial` is the base schema).
Alembic reads `DATABASE_URL` from the environment (falling back to `backend/.env` settings).

```bash
cd backend
alembic upgrade head        # apply
alembic downgrade -1        # roll back one revision
alembic current             # show current revision
alembic upgrade head --sql  # print PostgreSQL DDL without a live DB (offline check)
```

Application code never calls `Base.metadata.create_all()`; schema changes go through Alembic.

## Backend development (without Compose)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL to your PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs. Endpoints: `GET /api/v1/health`,
`POST|GET /api/v1/applications`, `GET|DELETE /api/v1/applications/{id}`,
`POST /api/v1/applications/{id}/api-key` (rotate), `POST|GET /api/v1/experiments`,
`GET|PATCH|DELETE /api/v1/experiments/{id}`, plus the SDK/runner surface
`POST /api/v1/experiments/{id}/runs`, `GET /api/v1/experiment-runs/{id}`,
`GET|POST /api/v1/experiment-runs/{id}/events`.

Discovery / ordinary observation:

- SDK ingest (`X-API-Key`): `POST /api/v1/task-executions/events`,
  `POST /api/v1/workers/events`, `POST /api/v1/tasks/discovery`.
- Catalog/read: `GET /api/v1/registered-tasks` (task catalog with execution aggregates),
  `GET /api/v1/registered-tasks/{id}`, `GET /api/v1/registered-tasks/{id}/executions`,
  `PATCH /api/v1/registered-tasks/{id}/observation` (`OBSERVING`/`DISABLED`/`DISCOVERED`),
  `GET /api/v1/applications/{id}/registered-tasks`.
- Executions: `GET /api/v1/task-executions` (filters: `target_app_id`, `task_name`, `status`,
  `celery_task_id`), `GET /api/v1/task-executions/{id}` (detail + events),
  `GET /api/v1/task-executions/{id}/events`.
- Workers: `GET /api/v1/workers`, `GET /api/v1/workers/{id}`.
- SDK convenience: `GET /api/v1/observation/workers`, `GET /api/v1/observation/ping`.

List endpoints accept `skip`/`limit` and return `{items, total, skip, limit}`.

### Authentication boundary

The dashboard/control endpoints are **not** authenticated yet (foundation limitation). The
SDK/runner endpoints require `X-API-Key`:

- `POST /applications` returns the plaintext key **once**; only its SHA-256 hash is stored.
- `POST /applications/{id}/api-key` rotates it (the previous key stops working immediately).
- A key is scoped to its application. Creating a run for, reading, or appending events to another
  application's run returns `404` on purpose, so the API does not reveal that the run exists.
- `POST /experiment-runs/{id}/events` always records `source="SDK"` (the caller cannot spoof it),
  requires a timezone-aware `occurred_at` (or server time), and treats `event_id` as an idempotency
  key: a repeat returns `200` with the stored event instead of appending a duplicate.
- Observation ingest derives the application from the API key, so an SDK cannot write telemetry for
  another application. A reported `veriq_run_id` is linked only when that run belongs to the
  authenticated application; otherwise it is ignored and ordinary telemetry is still stored.
- `event_id` on `/task-executions/events` is the per-execution idempotency key. `execution_id` is the
  attempt identity, so retries and redeliveries get separate rows even with the same Celery task id.

## Frontend development (without Compose)

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173, proxies /api to http://localhost:8000
npm run build  # tsc + vite build
```

Set `VITE_API_URL` (see `frontend/.env.example`) to point at a backend on another origin;
otherwise the Vite proxy is used. The UI shows loading, empty, and error states and uses only
real API data — there is no fake/demo data.

## Python SDK and isolated workers

The SDK lives in [sdk/](sdk/README.md) and installs independently:

```bash
pip install -e sdk          # or: pip install -e "sdk[dev]"
```

```python
import os
from veriq import VeriQ

with VeriQ(api_url=os.environ["VERIQ_API_URL"], api_key=os.environ["VERIQ_API_KEY"]) as veriq:
    receipt = veriq.send_event(
        experiment_run_id="<run-id>",
        event_type="sdk.test_event",
        payload={"message": "SDK communication successful"},
    )
```

Celery applications install automatic observation once:

```python
from veriq.celery import integrate

integrate(celery_app, veriq)   # task lifecycle, worker identity, queues, discovery
veriq.checkpoint("payment_charged")   # report-only, inside a task
```

The integration uses `task_prerun`, `task_postrun`, `task_failure`, `task_retry`,
`worker_ready`, `heartbeat_sent` and `worker_shutdown`; see [sdk/README.md](sdk/README.md#celery-integration-automatic-observation).
Explicit SDK calls raise typed `veriq.VeriQError` subclasses (config, connection, timeout,
authentication, validation, server); nothing is swallowed and no retries happen automatically.
The Celery integration and `checkpoint` are fail-open: reporting errors are logged, never raised into
task code. If you retry an explicit call manually, reuse the same `event_id` so the backend
deduplicates.

The reference Docker Compose integration for a Celery target application is
[examples/celery-target-app](examples/celery-target-app/README.md): Redis broker, a normal worker on
`normal`, and a dedicated `veriq-worker` on `veriq.test` with `--concurrency=1`, both from the same
image and task code, with the SDK installed in the image. It is development/test-only and exposes no
Docker socket.

Target applications need two variables (see the example's `.env.example`):

| Variable | Purpose |
|---|---|
| `VERIQ_API_URL` | Backend base URL, e.g. `http://host.docker.internal:8000` |
| `VERIQ_API_KEY` | Key returned by `POST /api/v1/applications` (shown once) |

## Reliability runtime (execution)

The runner executes one approved test case at a time. It provisions an isolated Docker network with
its own Redis broker and PostgreSQL database, starts the application's **own image** on a dedicated
queue with `--concurrency=1`, submits the task with correlation headers, injects one controlled fault,
observes attempts and recovery, records a verdict, and removes everything again.

```text
VALIDATING → PROVISIONING → PREPARING_FAULT → STARTING → RUNNING → INJECTING
           → OBSERVING_RECOVERY → EVALUATING → FINALIZING → COMPLETED/FAILED/CANCELLED
```

Verdicts are exactly `PASS`, `FAIL`, `INCONCLUSIVE`, `INVALID_RUN` and `ERROR`, and are stored
separately from the lifecycle state. `ERROR` means VeriQ's infrastructure failed, never that the
application failed. Supported scenarios: `dependency_timeout`,
`successful_operation_lost_response` (real threaded HTTP proxy), `duplicate_message_delivery`,
`database_connection_interruption` (real TCP proxy in front of PostgreSQL) and
`worker_termination` (only through the runner supervisor).

API: `PUT|GET /applications/{id}/runtime-profile`, `GET /applications/{id}/runner/capabilities`,
`POST /applications/{id}/test-plans/{plan}/runs`, `GET /applications/{id}/test-runs[/{run}]`,
`POST /applications/{id}/test-runs/{run}/cancel` and
`POST /applications/{id}/test-runs/recover-interrupted`.

```bash
# Real end-to-end check (backend running with Docker access and a reachable callback URL):
cd backend && python scripts/runtime_e2e.py --image veriq-celery-target-worker:latest
```

The script registers an application, sets a Docker runtime profile, discovers a task from a real
worker, approves a plan, starts one run and prints the verdict with its fault, recovery, worker and
cleanup evidence. See [`docs/reliability-runtime.md`](docs/reliability-runtime.md) for the full model,
isolation boundaries and limitations.

## Testing

Backend tests use an **isolated throwaway SQLite database** (in-memory per test, schema from
`Base.metadata`) so they never touch your development PostgreSQL database. The models' JSONB
columns use `with_variant(JSON, "sqlite")`, so they are JSONB on PostgreSQL and plain JSON under
SQLite. Alembic migrations are verified separately with `alembic upgrade head --sql`.

```bash
pip install -r backend/requirements-dev.txt
pip install -e "sdk[dev]"       # SDK + Celery, used by the Celery integration tests
cd backend && python -m pytest tests -q

cd sdk && python -m pytest -q   # SDK unit tests, HTTP fully mocked

cd frontend && npm install && npm run build   # tsc + Vite production build
```

Backend coverage: health/DB connectivity, application create/duplicate/empty-name/delete rules,
experiment create with valid & invalid application IDs, invalid timeouts, editing a non-DRAFT
experiment (409), run-number uniqueness per experiment, event association/ordering, API-key
issuance/rotation/scoping, run config snapshots, and idempotent event ingestion. Discovery/observation
coverage adds worker registration/heartbeat/shutdown idempotency, stale-worker marking, queue
discovery, duplicate task discovery, observation enable/disable (telemetry dropped, discovery kept),
ordinary executions without an experiment, experiment-linked executions with ownership checks,
multiple attempts per Celery task id, event idempotency, pagination and API-key enforcement. The
backend suite also drives the real SDK against the app in-process
(`tests/test_sdk_integration.py`).

Runtime coverage adds environment plans and profile validation, readiness reports, the simulated
backend (success, provisioning/readiness/worker failures, cleanup errors), injector behaviour and
validation (HTTP delay vs lost response, database interrupt/restore, duplicate submission, worker
termination), the recovery policy/evaluator verdict matrix, orchestrator lifecycle tests with
scripted application behaviour (checkpoint activation, fault that never triggers, cancellation,
runner infrastructure failure, configuration drift, per-case isolation), the runtime API (profile,
capabilities, start, read, ownership, cancel, recover) and run-scoped credential authentication and
revocation.

SDK coverage: configuration validation and URL normalization, event serialization/unique IDs/UTC
timestamps, auth header construction, success, 401/403, 404/422, 5xx, connection failure, timeout,
cleanup, and no credential logging. Celery coverage adds all supported signals, duplicate-terminal
suppression, retry, per-attempt execution ids, missing/present experiment headers, checkpoint
reporting, worker identity + queue discovery, multiple Celery apps, eager-mode skipping, transport
failure resilience, concurrent context isolation, and a real in-process Celery worker test.

## Current limitations & future work

- **No experiment execution engine** for the legacy `experiments`/`experiment_runs` tables: those runs
  can still be created through the API with a frozen config snapshot, but execution happens only
  through the reliability runtime (`test_case_runs`) and only for approved plan cases.
- **No business-effect verification.** The runtime verdict covers execution and recovery only
  (`scope: execution_recovery_only`); invariant checking against the application's own data is a
  later milestone.
- **No invariant checker, no multi-tenant scheduling, no parallel runs per case.** Isolation is
  Docker-only and intended for trusted applications, not as a security boundary.
- **Dashboard endpoints are unauthenticated**; only the SDK/runner endpoints use API keys. This is the
  existing foundation boundary, not a new decision.
- Worker staleness is computed lazily on read (120s threshold) rather than by a background job.
- Discovery uses the Celery app's registered tasks and best-effort worker consumer information.
  Celery remote-control inspection is optional/disabled in many deployments and is not required.
- Observation filtering happens in the backend (the SDK keeps reporting and the API drops telemetry
  for `DISABLED` tasks) to avoid an extra backend lookup on every task execution.
- No SDK event buffering, batching, retry/backoff, offline delivery or advanced payload redaction.
- Auth, multi-tenancy, and production deployment config are not included.
- The frontend uses state-based navigation rather than a router dependency (matching the original
  foundation decision), so deep links are not supported.

## Decisions to review before proceeding

1. **Timeout ceiling**: 3600s chosen as the "reasonable upper limit"; adjust if experiments need longer.
2. **Invalid application reference returns 422** (validation) rather than 404 — consistent with
   request-body validation; change if you prefer 400/404 semantics.
3. **Duplicate application name returns 409** (from the DB unique constraint).
4. **Test isolation via SQLite JSON variant** rather than a second PostgreSQL database — fast and
   hermetic; Alembic DDL is verified offline against PostgreSQL.
5. **Frontend uses state-based navigation** instead of react-router to keep dependencies minimal.
6. **Compose is development-only** (Vite dev server + uvicorn); production serving is out of scope.
