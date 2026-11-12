# Celery target application (VeriQ reference integration)

A deliberately small Celery application showing how a developer wires an
**isolated VeriQ experiment worker** next to production-like work.

```text
docker compose network
├── redis          broker (:6379, not published)
├── target-db      the target application's own PostgreSQL (test data)
├── worker         celery -Q normal --concurrency=2
└── veriq-worker   celery -Q veriq.test --concurrency=1 --hostname=veriq@...
                   + VERIQ_API_URL / VERIQ_API_KEY
```

Both workers are built from **one image** and import **one Celery app**, so they
run the same `app/tasks.py` code. The only differences are the queue they consume
and the concurrency. `veriq-worker` has no Docker socket, no published ports, and
no access to the `normal` queue.

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
cp .env.example .env      # set VERIQ_API_KEY, TARGET_POSTGRES_PASSWORD, ...
```

`VERIQ_API_URL=http://host.docker.internal:8000` reaches a backend running on your
machine (compose maps it via `extra_hosts`). If the backend runs in the same
compose network, use `http://backend:8000` instead.

## 3. Start it

```bash
docker compose up --build
```

Watch each worker's queue subscription in its startup banner:

```bash
docker compose logs worker      | grep -A2 queues
docker compose logs veriq-worker | grep -A2 queues
```

Expected: `normal` on `worker`, `veriq.test` on `veriq-worker`, each with the
same task list (`app.tasks.charge_order`, `app.tasks.veriq_probe`).

## 4. Submit work to each queue

```bash
# Normal business work -> worker
docker compose exec worker python -c "from app.tasks import charge_order; print(charge_order.delay('order-1', 500).id)"

# Experiment-queue work -> veriq-worker only
docker compose exec worker python -c "from app.tasks import charge_order; print(charge_order.apply_async(('order-2', 500), queue='veriq.test').id)"
```

Each worker's log names the task it executed. A task sent to `veriq.test` must
never appear in the `worker` log.

## 5. Prove the SDK path from inside the isolated worker

1. Create an experiment and a run for the registered application (the runner will
   do this later; for now use the API with your API key):

   ```bash
   KEY=vq_...
   curl -s -X POST http://localhost:8000/api/v1/experiments \
     -H 'Content-Type: application/json' \
     -d '{"target_app_id":"<app-id>","name":"probe","task_name":"app.tasks.veriq_probe","scenario":"crash_after_commit"}'

   curl -s -X POST http://localhost:8000/api/v1/experiments/<experiment-id>/runs \
     -H "X-API-Key: $KEY"
   ```

2. Dispatch the probe task to the VeriQ queue with the run ID from the response:

   ```bash
   docker compose exec veriq-worker python -c "
   from app.tasks import veriq_probe
   veriq_probe.apply_async(('<run-id>',), queue='veriq.test')
   "
   ```

3. Confirm the event was stored:

   ```bash
   curl -s http://localhost:8000/api/v1/experiment-runs/<run-id>/events -H "X-API-Key: $KEY"
   ```

`veriq_probe` is a **manual** SDK call. It is not Celery instrumentation: no
signals, no automatic run-id generation, no checkpoints. Those are future
milestones.

## What is intentionally missing

- No failure injection, worker killing or Docker control (runner milestone).
- No automatic task instrumentation and no checkpoint coordination.
- The sample tasks do not query PostgreSQL, so no migrations are needed; both
  workers still receive `TARGET_DATABASE_URL` because real tasks would.
- No health check on the Celery workers themselves (Celery has no HTTP endpoint);
  verify them from their logs.

## Notes for adapting this to a real application

- Install the SDK into the real image (`pip install veriq` once published) and
  keep exactly the same application code in both workers.
- Keep the VeriQ queue name distinct (`veriq.test`) and never subscribe a normal
  worker to it.
- Point `TARGET_DATABASE_URL` at a disposable test database, and use test-mode
  credentials for any payment provider.
- Keep `--concurrency=1` on the VeriQ worker: it is what lets the future runner
  attribute one task to one process.
