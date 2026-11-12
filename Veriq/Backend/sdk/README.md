# VeriQ Python SDK

The VeriQ SDK is a small, synchronous Python client that a **target application**
installs so it can report experiment events to a **VeriQ backend**.

- **VeriQ backend** (this repository's `backend/`): FastAPI control API, metadata
  database, experiments, runs and event storage. It decides what is authorized.
- **VeriQ SDK** (this package): a transport. It builds one structured event,
  authenticates with an API key, and POSTs it. It has no database access and no
  knowledge of VeriQ's internal models.

The SDK deliberately does **not** control Docker, kill processes, retry
automatically, instrument Celery signals, generate execution identities, or
coordinate checkpoints. Those belong to the runner and later milestones.

## Supported Python

- Python **3.9+** (CPython). The backend itself requires Python 3.12+; the SDK is
  intentionally more permissive because it is installed into someone else's
  application.
- Only dependency: [`httpx`](https://www.python-httpx.org/) (`>=0.25,<1.0`).

## Install for local development

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e sdk                # editable install of this package
pip install -e "sdk[dev]"         # plus pytest, for the SDK test suite
```

`src/` layout, so `veriq` is importable from any working directory after install.

## Configuration

The SDK never reads environment variables itself; pass values explicitly (the
example application reads them with `os.environ` and passes them in).

| Setting   | Required | Default | Notes |
|-----------|----------|---------|-------|
| `api_url` | yes      | –       | `http://` or `https://`. A trailing `/` and a trailing `/api/v1` are both accepted and normalized. Credentials in the URL are rejected. |
| `api_key` | yes      | –       | Issued once by `POST /api/v1/applications`. Must not contain whitespace. |
| `timeout` | no       | `10.0`  | Seconds, bounded to `0 < timeout <= 120`. |

```python
import os
from veriq import VeriQ

veriq = VeriQ(
    api_url=os.environ["VERIQ_API_URL"],
    api_key=os.environ["VERIQ_API_KEY"],
)
```

Or build the configuration separately:

```python
from veriq import VeriQ, VeriQConfig

config = VeriQConfig(api_url="http://localhost:8000", api_key="vq_...", timeout=5)
veriq = VeriQ(config)
```

`repr(config)` and `repr(veriq)` always print `api_key='***'`; error messages
never contain the key. The key is sent only in the `X-API-Key` header.

## Sending an event

```python
with VeriQ(api_url="http://localhost:8000", api_key="vq_...") as veriq:
    receipt = veriq.send_event(
        experiment_run_id="6d0f0b1e-...",      # UUID string or uuid.UUID
        event_type="sdk.test_event",
        payload={"message": "SDK communication successful"},
    )
print(receipt.server_event_id, receipt.duplicate)
```

- `occurred_at` defaults to the current timezone-aware UTC time; a supplied
  aware datetime is converted to UTC. Naive datetimes are rejected.
- `event_id` defaults to a fresh UUID v4. It doubles as the backend's
  **idempotency key**: re-sending with the same `event_id` returns the stored
  event (`receipt.duplicate is True`) instead of appending a second one.
- `payload` must be a JSON object (`dict`) or omitted. Never pass secrets,
  credentials, or raw business objects.
- `close()` is explicit and idempotent; the context manager does it for you.

The client keeps one reusable `httpx.Client` for its whole lifetime, so create
the client once per worker process rather than per event.

## Endpoints used

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/experiment-runs/{run_id}/events` | Append an SDK event. `201` = recorded, `200` = duplicate `event_id` (already recorded). |

The backend forces `source = "SDK"`, authenticates the API key, and verifies the
run belongs to the authenticated application. Runs themselves are created by the
runner via `POST /api/v1/experiments/{experiment_id}/runs` (also API-key
authenticated). There is no execution engine yet: creating a run does not start
a worker or a task.

## Error handling

All failures derive from `veriq.VeriQError`:

| Exception | When |
|-----------|------|
| `VeriQConfigError` | invalid URL/key/timeout, or conflicting constructor arguments (also a `ValueError`) |
| `VeriQClientClosedError` | using a client after `close()` |
| `VeriQConnectionError` | no connection to the backend |
| `VeriQTimeoutError` | the backend did not answer within `timeout` |
| `VeriQAuthenticationError` | HTTP `401`/`403` (missing/invalid key) |
| `VeriQValidationError` | HTTP `400`/`404`/`409`/`422`, or locally invalid event data |
| `VeriQServerError` | HTTP `5xx` |
| `VeriQHTTPError` | base class for the HTTP errors; other unexpected statuses |

```python
from veriq import VeriQTimeoutError, VeriQAuthenticationError

try:
    veriq.send_event(run_id, "sdk.test_event", {"message": "hi"})
except VeriQAuthenticationError:
    ...  # fix the key; do not retry
except VeriQTimeoutError:
    ...  # backend slow/unreachable; retrying is the caller's choice
```

**No automatic retries.** This milestone does not retry anything. If your own
code retries a failed submission, reuse the same `event_id` (or send the same
`VeriQEvent` again) so the backend deduplicates it. Never retry `401`/`403` or
`4xx` validation failures; a `5xx` or timeout is safe to retry with the same ID.

### Behaviour when submission fails

The SDK raises; it does not swallow errors. Because it is embedded in a target
application's worker, the failure of `send_event` propagates into that task
unless the caller handles it. There is no fail-open checkpoint behaviour yet, so
an event failure is simply an event failure — it never changes your task's
business outcome by itself, but it will also not be recorded.

## Isolated Celery worker setup

The reference integration lives in [`examples/celery-target-app`](../examples/celery-target-app/README.md):
a Redis broker, a normal worker consuming `normal`, and a `veriq-worker`
consuming only `veriq.test` with `--concurrency=1`, both built from the same
image and task definitions. The SDK is installed inside that image and reads
`VERIQ_API_URL` / `VERIQ_API_KEY` from the environment.

The SDK is not involved in that isolation: the worker's queue and concurrency
are set on the worker's command line by whoever deploys it. The SDK only reports
events for a run ID it is given.

## Security and test-environment recommendations

- Treat an API key like a password: inject it as a secret/env var, never bake it
  into images, compose files, logs or notebooks. Rotate via
  `POST /api/v1/applications/{id}/api-key` (the old key stops working at once).
- Point VeriQ at a **test** application and a dedicated test database. The
  backend stores metadata only, but your tasks will run against whatever the
  worker is configured with.
- Use test-mode payment-provider credentials. Nothing in VeriQ requires real
  money movement, and the sample tasks call no external provider.
- The example's `veriq-worker` gets no Docker socket and no host ports. Keep it
  that way; Docker control belongs to the runner.
- Event `payload` values are stored as evidence. Keep them small and free of
  personal data, tokens, or task arguments.

## Current limitations

Intentionally **not** implemented in this milestone:

- Celery signal instrumentation, task lifecycle observation
- automatic execution-id generation or experiment header propagation
- signed experiment tokens and manual checkpoints
- checkpoint waiting/synchronization and failure injection
- Docker/process control (runner responsibility)
- business invariant checking, arbitrary SQL execution
- automatic retries, batching, async client
- Kubernetes/ECS or non-Celery queue integrations
- fail-open behaviour when VeriQ is unreachable

## Development

```bash
pip install -e "sdk[dev]"
cd sdk && python -m pytest        # fully mocked HTTP, no backend required
```

Run the backend suite too; it includes an in-process end-to-end test that drives
this SDK against the real FastAPI app:

```bash
pip install -r backend/requirements-dev.txt
cd backend && python -m pytest tests
```
