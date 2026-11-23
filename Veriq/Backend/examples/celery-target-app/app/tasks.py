"""Sample tasks shared by the normal worker and the VeriQ worker.

Every task is ordinary business code. The only VeriQ-specific calls are the
report-only ``checkpoint`` calls, which are no-ops when the SDK is not
configured. The workers are instrumented automatically by
``app.veriq_setup.integrate_celery``.
"""

from __future__ import annotations

import os
import sqlite3
import time
import json
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.veriq_setup import checkpoint

# The sample application's own storage. SQLite keeps the reference app
# dependency-free while still giving a real database effect to measure.
TARGET_SQLITE_PATH = os.environ.get("TARGET_SQLITE_PATH", "/tmp/veriq-target.db")


@celery_app.task(name="app.tasks.charge_order")
def charge_order(order_id: str, amount_cents: int) -> dict:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")

    checkpoint("order_validated")

    payment_proxy = os.environ.get("TARGET_PAYMENT_URL")
    payment_url = (
        f"{payment_proxy.rstrip('/')}/charge"
        if payment_proxy
        else "http://mock-payment-service/charge"
    )
    request = urllib.request.Request(
        payment_url,
        data=json.dumps({
            "order_id": order_id,
            "amount_cents": amount_cents
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"payment dependency returned HTTP {exc.code}"
        ) from exc

    checkpoint("payment_charged")

    return payload


@celery_app.task(name="app.tasks.checkpointed_payment")
def checkpointed_payment(order_id: str, amount_cents: int = 500) -> dict:
    """Successful task with several report-only checkpoints.

    Checkpoints never pause the task; they only add timeline events.
    """
    checkpoint("payment_started", {"order_id": order_id})
    checkpoint("payment_charged")
    checkpoint("ledger_written", {"amount_cents": amount_cents})
    return {"order_id": order_id, "status": "settled"}


@celery_app.task(name="app.tasks.fail_order")
def fail_order(order_id: str) -> dict:
    """Failing task: raises after recording one checkpoint."""
    checkpoint("order_loaded", {"order_id": order_id})
    raise RuntimeError(f"simulated downstream failure for order {order_id}")


@celery_app.task(
    name="app.tasks.retry_payment",
    bind=True,
    max_retries=2,
    default_retry_delay=1,
)
def retry_payment(self, order_id: str, attempt: int = 0) -> dict:
    """Task that requests Celery retries before succeeding.

    Each attempt is a distinct execution with its own ``execution_id`` while the
    Celery task id may be reused by Celery's retry machinery.
    """
    checkpoint("retry_attempt", {"attempt": attempt})
    if attempt < 2:
        raise self.retry(countdown=1, kwargs={"order_id": order_id, "attempt": attempt + 1})
    return {"order_id": order_id, "status": "paid", "attempts": attempt + 1}


@celery_app.task(name="app.tasks.concurrent_probe")
def concurrent_probe(index: int, sleep_seconds: float = 0.5) -> dict:
    """Concurrent task used to prove executions are tracked independently."""
    checkpoint("probe_started", {"index": index})
    time.sleep(sleep_seconds)
    checkpoint("probe_finished", {"index": index})
    return {"index": index, "pid": os.getpid()}


@celery_app.task(name="app.tasks.veriq_probe")
def veriq_probe(experiment_run_id: str, message: str = "SDK communication successful") -> dict:
    """Legacy manual probe: report one experiment event for an existing run."""
    from veriq import VeriQ

    api_url = os.environ.get("VERIQ_API_URL")
    api_key = os.environ.get("VERIQ_API_KEY")
    if not api_url or not api_key:
        raise RuntimeError(
            "VERIQ_API_URL and VERIQ_API_KEY must be set for the veriq-worker service"
        )

    with VeriQ(api_url=api_url, api_key=api_key) as veriq:
        receipt = veriq.send_event(
            experiment_run_id=experiment_run_id,
            event_type="sdk.test_event",
            payload={"message": message},
        )
    return {
        "server_event_id": str(receipt.server_event_id),
        "duplicate": receipt.duplicate,
    }


@celery_app.task(name="app.tasks.fetch_reference_data")
def fetch_reference_data(
    url: str = "https://example.com", timeout_seconds: int = 5
) -> dict:
    """Task with an HTTP dependency, used to plan dependency-failure scenarios.

    ``after_http_response`` is reported *after* the request completed, so a
    checkpoint-based test selected there runs after the external call.
    """
    checkpoint("before_http_request", {"url": url})
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        body = response.read()
        status_code = response.status
    checkpoint("after_http_response", {"status": status_code, "bytes": len(body)})
    return {"url": url, "status": status_code, "bytes": len(body)}


@celery_app.task(name="app.tasks.record_document")
def record_document(document_id: str, content_hash: str = "hash-test-001") -> dict:
    """Task that writes one row to the application database.

    The primary key makes a duplicate delivery fail loudly (an application-level
    duplicate effect), which is exactly what effect measurements are for. Cleanup
    is expected to remove test-owned rows only.
    """
    checkpoint("before_database_save", {"document_id": document_id})
    with sqlite3.connect(TARGET_SQLITE_PATH) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO documents (document_id, content_hash, created_at) "
            "VALUES (?, ?, ?)",
            (document_id, content_hash, datetime.now(timezone.utc).isoformat()),
        )
    checkpoint("after_database_save", {"document_id": document_id})
    return {"document_id": document_id, "status": "stored"}


@celery_app.task(name="app.tasks.record_document_pg")
def record_document_pg(document_id: str, content_hash: str = "hash-test-001") -> dict:
    """Same effect as :func:`record_document`, but on PostgreSQL.

    PostgreSQL is what the isolated runner provisions, and pointing this task at
    the database fault proxy is what makes a real connection interruption test
    possible. The primary key also makes a duplicate delivery fail loudly, which
    is an application-level duplicate effect (not a VeriQ verdict).
    """
    checkpoint("before_database_save", {"document_id": document_id, "driver": "psycopg"})
    database_url = os.environ.get("TARGET_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TARGET_DATABASE_URL must be set for record_document_pg")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    import psycopg

    with psycopg.connect(database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS documents_pg ("
                "document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cursor.execute(
                "INSERT INTO documents_pg (document_id, content_hash) VALUES (%s, %s)",
                (document_id, content_hash),
            )
        connection.commit()
    checkpoint("after_database_save", {"document_id": document_id})
    return {"document_id": document_id, "status": "stored"}


@celery_app.task(name="app.tasks.slow_operation")
def slow_operation(seconds: float = 5.0) -> dict:
    """Long-running task with boundaries on both sides of the slow section.

    Used for worker-termination tests: terminating between ``before_slow_work``
    and ``after_slow_work`` proves the worker was executing this task.
    """
    checkpoint("before_slow_work", {"seconds": seconds})
    time.sleep(max(0.0, float(seconds)))
    checkpoint("after_slow_work", {"seconds": seconds})
    return {"status": "completed", "seconds": seconds, "pid": os.getpid()}


@celery_app.task(name="app.tasks.mixed_outcomes")
def mixed_outcomes(fail: bool = False) -> dict:
    """Single task used to exercise both outcomes; handy for demos."""
    execution = str(uuid.uuid4())
    checkpoint("mixed_started", {"execution_marker": execution})
    if fail:
        raise ValueError("requested failure")
    return {"status": "ok", "execution_marker": execution}
