# Celery target application (VeriQ reference integration)

A small but complete Celery application demonstrating VeriQ's discovery and
ordinary execution observation. It is deliberately boring business code: VeriQ
instruments it through Celery signals, not through task rewrites.

```text
docker compose network
├── redis          broker (:6379, not published)
├── api            FastAPI :8100 — enqueues example tasks, initialises the SDK
├── worker         celery -A app.worker -Q normal      --concurrency=2
└── veriq-worker   celery -A app.worker -Q veriq.test  --concurrency=1 --hostname=veriq@...
```

Both workers are built from **one image** and import **one Celery app**, so they
run the same `app/tasks.py` code. The differences are the queue they consume and
the concurrency. The normal worker is instrumented too: ordinary telemetry does
not require an experiment or the VeriQ worker.

## 1. Register the application and get an API key

With the VeriQ backend running (`docker compose up --build` + `alembic upgrade head`
in the repository root):

```bash
curl -s -X POST http://localhost:8000/api/v1/applications \
  -H 'Content-Type: application/json' \
  -d '{"name":"celery-target-app","environment":"test"}'
```

The response contains `id` and `api_key` (`vq_...`). The key is shown **once**;
rotate it later with `POST /api/v1/applications/{id}/api-key`.

## 2. Configure the example

```bash
cd examples/celery-target-app
cp .env.example .env      # set VERIQ_API_KEY, VERIQ_API_URL, ...
```

`VERIQ_API_URL=http://host.docker.internal:8000` reaches a backend running on your
machine (compose maps it via `extra_hosts`). If the backend runs in the same
compose network, use `http://backend:8000` instead.

## 3. Start it

```bash
docker compose up --build
```

What happens at startup:

- `api` (FastAPI) imports the Celery app and calls `integrate(...)`, reporting
  every registered task to `POST /api/v1/tasks/discovery`.
- Each worker's `worker_ready` reports its `worker_instance_id`, PID,
  process-start identity, registered tasks and queues.
- `heartbeat_sent` refreshes `last_seen_at` every 30 seconds (throttled).

Verify discovery:

```bash
curl -s 'http://localhost:8000/api/v1/registered-tasks?limit=100'
curl -s 'http://localhost:8000/api/v1/workers?limit=100'
```

Both workers should appear, `worker` with `normal` and `veriq-worker` with
`veriq.test`. Historical worker rows stay after shutdown and become `OFFLINE`
when heartbeats stop.

## 4. Trigger example tasks

The FastAPI app exposes simple endpoints:

| Endpoint | Task | Outcome |
|---|---|---|
| `POST /tasks/charge-order` | `app.tasks.charge_order` | success + checkpoints |
| `POST /tasks/checkpointed-payment` | `app.tasks.checkpointed_payment` | success + 3 checkpoints |
| `POST /tasks/fail-order` | `app.tasks.fail_order` | raises `RuntimeError` |
| `POST /tasks/retry-payment` | `app.tasks.retry_payment` | requests 2 retries, then succeeds (VeriQ queue) |
| `POST /tasks/concurrent-probe?count=3` | `app.tasks.concurrent_probe` | 3 concurrent executions |

```bash
curl -X POST 'http://localhost:8100/tasks/charge-order?order_id=order-1&amount_cents=500'
curl -X POST 'http://localhost:8100/tasks/fail-order?order_id=order-2'
curl -X POST 'http://localhost:8100/tasks/retry-payment?order_id=order-3'
curl -X POST 'http://localhost:8100/tasks/concurrent-probe?count=3'
```

You can also dispatch from a worker container:

```bash
docker compose exec worker python -c "from app.tasks import charge_order; print(charge_order.delay('order-9', 500).id)"
# Same task definition on the isolated queue:
docker compose exec worker python -c "from app.tasks import charge_order; print(charge_order.apply_async(('order-10', 500), queue='veriq.test').id)"
```

## 5. Inspect executions and timelines

```bash
# List ordinary executions (no experiment required)
curl -s 'http://localhost:8000/api/v1/task-executions?limit=20'

# One execution with its events
curl -s 'http://localhost:8000/api/v1/task-executions/<execution-db-id>'

# Open the dashboard at http://localhost:5173 → Task catalog → a task
```

Each attempt has its own `execution_id`; retries share the Celery task id but
appear as separate rows. `TASK_CHECKPOINT` events show where the task reached.

## 6. Observation selection

Tasks are discovered independently of telemetry. The dashboard (or API) can
disable observation for one task:

```bash
curl -s -X PATCH 'http://localhost:8000/api/v1/registered-tasks/<task-db-id>/observation' \
  -H 'Content-Type: application/json' -d '{"status":"DISABLED"}'
```

New execution events for that task are acknowledged but not stored. Discovery
and heartbeats continue, so the task stays in the catalog with status
`DISABLED`. Set `OBSERVING` (or `DISCOVERED`) to resume storage.

## 7. Experiment-linked executions (compatibility)

The legacy manual probe still works for existing experiment runs:

```bash
KEY=vq_...
curl -s -X POST http://localhost:8000/api/v1/experiments \
  -H 'Content-Type: application/json' \
  -d '{"target_app_id":"<app-id>","name":"probe","task_name":"app.tasks.veriq_probe","scenario":"crash_after_commit"}'

curl -s -X POST http://localhost:8000/api/v1/experiments/<experiment-id>/runs -H "X-API-Key: $KEY"

curl -X POST 'http://localhost:8100/tasks/veriq-probe/<run-id>'
curl -s http://localhost:8000/api/v1/experiment-runs/<run-id>/events -H "X-API-Key: $KEY"
```

To link ordinary task executions to a run, dispatch with VeriQ headers:

```python
charge_order.apply_async(
    ("order-11", 500),
    headers={"veriq_run_id": "<run-id>", "veriq_operation_id": "<uuid>"},
)
```

The backend validates that the run belongs to the authenticated application. A
foreign/stale run id is ignored; the execution is still stored without a link.

## What is intentionally missing

- No failure injection, worker killing or Docker control (runner milestone).
- No checkpoint synchronization, pauses or worker termination.
- The sample tasks do not query PostgreSQL; both workers still receive
  `TARGET_DATABASE_URL` because real tasks would.
- No health check on the Celery workers themselves (Celery has no HTTP endpoint);
  verify them from their logs and the VeriQ dashboard.

## Notes for adapting this to a real application

- Install the SDK into the real image (`pip install veriq[celery]` once
  published) and keep exactly the same application code in both workers.
- Call `integrate(celery_app, veriq)` once per process (for example in your worker
  entrypoint and API startup).
- Keep the VeriQ queue name distinct (`veriq.test`) and never subscribe a normal
  worker to it.
- Point `TARGET_DATABASE_URL` at a disposable test database, and use test-mode
  credentials for any payment provider.
- Keep `--concurrency=1` on the VeriQ worker: it is what lets the future runner
  attribute one task to one process.
