"""Sample tasks shared by the normal worker and the VeriQ worker.

Every task is ordinary business code. The only VeriQ-specific calls are the
report-only ``checkpoint`` calls, which are no-ops when the SDK is not
configured. The workers are instrumented automatically by
``app.veriq_setup.integrate_celery``.
"""

from __future__ import annotations

import os
import time
import uuid

from app.celery_app import celery_app
from app.veriq_setup import checkpoint


@celery_app.task(name="app.tasks.charge_order")
def charge_order(order_id: str, amount_cents: int) -> dict:
    """Successful task: pretends to charge an order."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    checkpoint("order_validated")
    checkpoint("payment_charged")
    return {"order_id": order_id, "amount_cents": amount_cents, "status": "charged"}


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


@celery_app.task(name="app.tasks.mixed_outcomes")
def mixed_outcomes(fail: bool = False) -> dict:
    """Single task used to exercise both outcomes; handy for demos."""
    execution = str(uuid.uuid4())
    checkpoint("mixed_started", {"execution_marker": execution})
    if fail:
        raise ValueError("requested failure")
    return {"status": "ok", "execution_marker": execution}
