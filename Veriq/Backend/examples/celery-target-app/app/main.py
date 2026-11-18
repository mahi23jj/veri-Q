"""FastAPI front door for the example target application.

It enqueues the same tasks both workers import. The API process also
initialises the VeriQ SDK so registered tasks are discovered before any worker
starts, which is exactly what a real integration would do.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException

from app import tasks as task_module
from app.celery_app import NORMAL_QUEUE, VERIQ_QUEUE, celery_app
from app.veriq_setup import integrate_celery

app = FastAPI(title="VeriQ Celery example target app", version="0.1.0")

# Best-effort discovery + integration; no-op when the SDK is not configured.
integrate_celery()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "queues": [NORMAL_QUEUE, VERIQ_QUEUE]}


@app.get("/tasks")
def list_tasks() -> dict:
    return {
        "tasks": sorted(
            name for name in celery_app.tasks if not name.startswith("celery.")
        )
    }


@app.post("/tasks/charge-order")
def run_charge_order(order_id: str = "order-1", amount_cents: int = 500) -> dict:
    result = task_module.charge_order.apply_async((order_id, amount_cents), queue=NORMAL_QUEUE)
    return {"celery_task_id": result.id, "queue": NORMAL_QUEUE}


@app.post("/tasks/checkpointed-payment")
def run_checkpointed_payment(order_id: str = "order-2") -> dict:
    result = task_module.checkpointed_payment.apply_async((order_id,), queue=NORMAL_QUEUE)
    return {"celery_task_id": result.id, "queue": NORMAL_QUEUE}


@app.post("/tasks/fail-order")
def run_fail_order(order_id: str = "order-3") -> dict:
    result = task_module.fail_order.apply_async((order_id,), queue=NORMAL_QUEUE)
    return {"celery_task_id": result.id, "queue": NORMAL_QUEUE}


@app.post("/tasks/retry-payment")
def run_retry_payment(order_id: str = "order-4") -> dict:
    # Sent to the isolated VeriQ queue so the dedicated worker retries it.
    result = task_module.retry_payment.apply_async((order_id,), queue=VERIQ_QUEUE)
    return {"celery_task_id": result.id, "queue": VERIQ_QUEUE}


@app.post("/tasks/concurrent-probe")
def run_concurrent_probe(count: int = 3) -> dict:
    if count < 1 or count > 20:
        raise HTTPException(status_code=422, detail="count must be between 1 and 20")
    ids = [
        task_module.concurrent_probe.apply_async((index, 0.5), queue=NORMAL_QUEUE).id
        for index in range(count)
    ]
    return {"celery_task_ids": ids, "queue": NORMAL_QUEUE}


@app.post("/tasks/veriq-probe/{run_id}")
def run_veriq_probe(run_id: str) -> dict:
    """Dispatch the legacy manual SDK-event probe to the VeriQ queue."""
    result = task_module.veriq_probe.apply_async((run_id,), queue=VERIQ_QUEUE)
    return {"celery_task_id": result.id, "queue": VERIQ_QUEUE}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("API_PORT", "8100")),
    )
