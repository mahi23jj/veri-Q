# Reliability runtime (execution, fault injection, recovery, verdicts)

This document describes the layer that actually runs an approved reliability test:
it provisions an isolated environment, starts a dedicated worker, injects one
controlled failure, observes what the application did, records a deterministic
verdict, and cleans everything up. It builds on
[`reliability-planning.md`](reliability-planning.md) and does not change it.

Planning stays a proposal. **Approval still executes nothing**: a run only starts
when a client calls the start endpoint for one approved test case.

## Pipeline

```text
approved plan revision ──► POST .../test-plans/{id}/runs   (explicit start)
        │
        ▼
VALIDATING ─► PROVISIONING ─► PREPARING_FAULT ─► STARTING ─► RUNNING ─► INJECTING
                                                                          │
                                                        OBSERVING_RECOVERY ┘
                                                                          │
                                                              EVALUATING ─► FINALIZING
                                                                          │
                                                             COMPLETED / FAILED / CANCELLED
```

| Stage | What happens |
|---|---|
| `VALIDATING` | The case, contract revision and approval are re-checked. An invalidated or stale case fails here with `INVALID_RUN`. |
| `PROVISIONING` | `DockerRuntime` creates a per-run network, a Redis broker and a PostgreSQL database, publishes readiness ports on loopback only, and waits until both answer. |
| `PREPARING_FAULT` | The scenario's injector is constructed and `prepare()`d (for the HTTP/DB proxies this binds the listening socket and resolves the real upstream). States: `PREPARING` → `ARMED`. |
| `STARTING` | The supervisor starts the application's **own image** with the isolated queue and `--concurrency=1`, injects the run-scoped SDK credential, and waits for both `worker_ready` and a discovery row for this run's queue. |
| `RUNNING` | The execution controller submits the task to the per-run broker with `veriq_operation_id` headers. |
| `INJECTING` | Automatic injectors fire immediately; checkpoint injectors fire when the worker reports the configured checkpoint; execution-triggered injectors fire as soon as the task is running. |
| `OBSERVING_RECOVERY` | The observer polls the observation tables until the recovery policy is satisfied or its deadline passes. A terminated worker is replaced by the supervisor before this window opens. |
| `EVALUATING` | The pure evaluator turns recorded facts into a verdict. No LLM, no heuristics: only observed evidence is used. |
| `FINALIZING` | Cleanup runs on every terminal path: fault release, worker stop, environment removal, credential revocation, verdict untouched. |

Lifecycle and verdict are separate columns. A run can be `FAILED` with the
verdict `INVALID_RUN` (the test never happened), or `COMPLETED` with `PASS`.

## Verdicts

| Verdict | Meaning |
|---|---|
| `PASS` | The fault was activated and recovery met every configured expectation. |
| `FAIL` | The fault was activated, evidence is complete, and recovery did not meet the policy (for example no second attempt, wrong terminal state, or deadline exceeded). |
| `INCONCLUSIVE` | Evidence is missing (for example no terminal execution event), or the run was cancelled / interrupted before evaluation. |
| `INVALID_RUN` | The intended test never happened: the case or contract drifted after approval, or the fault never triggered at a checkpoint. |
| `ERROR` | VeriQ's own infrastructure failed (provisioning, worker start, submission). Never blamed on the application. |

`verdict_detail` records the individual checks (`evidence_complete`,
`attempt_limit`, `terminal_state`, `recovery_deadline`, `redelivery`, ...) with
the observed and expected values.

## Recovery policy

The contract carries a `recovery` block, snapshotted into the plan case:

```json
{
  "max_attempts": 2,
  "per_attempt_timeout_seconds": 30,
  "recovery_deadline_seconds": 120,
  "expected_terminal_state": "SUCCEEDED",
  "expect_redelivery": true,
  "expect_retry": null,
  "settle_seconds": 3
}
```

* `expect_retry` is about the application *requesting* a retry; `expect_redelivery`
  is about the broker delivering the same logical message again. They are
  independent facts and are recorded separately (`retry_request_count`,
  `subsequent_attempt_count`).
* Celery redelivery is configuration, not an assumption: it requires
  `task_acks_late` (and, for worker loss, `task_reject_on_worker_lost`) plus a
  visibility timeout that expires inside the window. The reference application
  exposes all three as environment variables, and the profile sets them.
* Attempts are correlated, not guessed: the runner submits with
  `veriq_operation_id` (and `veriq_logical_job_id`, `veriq_test_run_id`), the SDK
  repeats it on every execution event, and the observer links
  `TaskExecution.veriq_operation_id == run.id`.

## Scenarios

| Scenario | Injector | Trigger | Implementation |
|---|---|---|---|
| `dependency_timeout` | threaded HTTP proxy | automatic | returns a delayed response for the first N requests |
| `successful_operation_lost_response` | threaded HTTP proxy | automatic | accepts the request, executes the upstream call, then drops the response |
| `duplicate_message_delivery` | execution controller | automatic | submits the same logical job as two independent messages (`redelivery_proven: false`) |
| `database_connection_interruption` | TCP proxy in front of PostgreSQL | automatic or checkpoint | kills the connection, then resumes accepting |
| `worker_termination` | supervisor | automatic or checkpoint | terminates the exact isolated worker, never a production one |

HTTP and database faults are real proxies on real sockets, not mocks. Duplicate
delivery is deliberately *not* presented as a broker redelivery.

## Isolation

* Per run: one Docker network, one Redis container, one PostgreSQL container,
  one worker container, all prefixed `veriq-<run-hash>` and removed at cleanup.
* Readiness ports bind to `127.0.0.1` only; the backend talks to the broker over
  the published loopback port, the worker uses the internal service name.
* The worker runs the application's own image and code, on a queue nothing else
  consumes, with `--concurrency=1`, `--pids-limit`, `no-new-privileges` and a
  `tmpfs` for the broker.
* **Not a security boundary.** It isolates state and traffic for trusted
  applications; it is not a sandbox for hostile code. Production workers are
  never touched: only containers created by this run are ever stopped.
* The backend process needs access to the Docker CLI. A backend running inside a
  container without a Docker socket cannot execute a Docker run; use the
  `simulated` runtime type for local demos (it is explicitly non-isolated).

## Credentials

Each run mints its own SDK key (`vq_run_...`) for the isolated worker. Only its
SHA-256 digest is stored (`runner_credentials`); the plaintext lives in the
worker's environment. The key is accepted by the SDK ingest endpoints while it is
unrevoked and unexpired, and is revoked during finalization. The application's
own key is never placed in the test container.

## API

| Endpoint | Purpose |
|---|---|
| `PUT/GET /applications/{id}/runtime-profile` | How the runner launches this application's image (image, queue, env, broker/database images, HTTP/DB adapter wiring). Secrets are rejected. |
| `GET /applications/{id}/runner/capabilities` | Runtime types, Docker availability, supported scenarios, timeouts. |
| `POST /applications/{id}/test-plans/{plan}/runs` | Start one approved, `READY` case (`case_id` or `case_key`). |
| `GET /applications/{id}/test-runs` | List runs (filter by lifecycle, verdict, plan). |
| `GET /applications/{id}/test-runs/{run}` | Lifecycle, verdict detail, environment, workers, fault events, recovery observation, runtime events. |
| `POST /applications/{id}/test-runs/{run}/cancel` | Request cancellation (idempotent; finalization still runs). |
| `POST /applications/{id}/test-runs/recover-interrupted` | Finalize runs left behind by a backend restart (verdict `INCONCLUSIVE`, environment cleaned by label). |

## Operating it

```bash
# Backend must be able to reach the worker callback and to run Docker.
RUNNER_ENABLED=true \
RUNNER_CALLBACK_BASE_URL=http://host.docker.internal:8000 \
uvicorn app.main:app --port 8000

# End-to-end check against real containers and a real worker.
python scripts/runtime_e2e.py --api-url http://127.0.0.1:8000 \
    --image veriq-celery-target-worker:latest
```

`scripts/runtime_e2e.py` registers an application, sets a Docker profile,
discovers the task from a real worker, approves a plan, starts one run and prints
the verdict, fault events, recovery evidence, worker states and cleanup state. It
exits non-zero unless the verdict is `PASS`.

Timeouts live in settings (`RUNNER_PROVISIONING_TIMEOUT_SECONDS`,
`RUNNER_WORKER_STARTUP_TIMEOUT_SECONDS`, `RUNNER_FAULT_ACTIVATION_TIMEOUT_SECONDS`,
`RUNNER_EXECUTION_TIMEOUT_SECONDS`, `RUNNER_RECOVERY_TIMEOUT_SECONDS`,
`RUNNER_FINALIZATION_TIMEOUT_SECONDS`, `RUNNER_TOTAL_TIMEOUT_SECONDS`) and are
independent of the plan's own recovery policy.

## Cleanup guarantees

Cleanup is idempotent and runs on every terminal path, including cancellation,
runner failure and recovery after a restart:

1. the fault is released (proxies closed, no further action accepted);
2. every worker of the run is stopped;
3. broker and database are stopped and removed by name, then the network;
4. the run-scoped credential is revoked;
5. the lifecycle state is written **without touching the verdict**.

Removal is by container/network name derived from the run, so it also works
without any in-memory handle after a backend restart.

## Deliberate limits

* No business-effect verification: the verdict is about execution and recovery
  only (`scope: execution_recovery_only`). Effect measurements remain planning
  input for a later milestone.
* One scenario per run, one worker at a time, one run per test case.
* Docker-only isolation; no Kubernetes, no remote hosts, no multi-tenant
  scheduling.
* Duplicate delivery proves an application-level duplicate message, not broker
  redelivery.
* The HTTP/DB proxies advertise themselves as `host.docker.internal`; a
  non-Docker-Desktop network needs `http.advertised_host` set accordingly.
