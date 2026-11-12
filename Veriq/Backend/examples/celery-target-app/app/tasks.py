"""Sample tasks.

``charge_order`` is ordinary business work consumed by the normal worker.
``veriq_probe`` is an explicit, manually invoked SDK call used to prove that the
isolated worker can reach the VeriQ backend. Nothing here is instrumented
automatically: there are no Celery signals, no run-id generation and no
checkpoint behaviour. That is the next milestone.
"""

from __future__ import annotations

import os

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.charge_order")
def charge_order(order_id: str, amount_cents: int) -> dict:
    """Pretend to charge an order; no external payment provider is called."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    return {"order_id": order_id, "amount_cents": amount_cents, "status": "charged"}


@celery_app.task(name="app.tasks.veriq_probe")
def veriq_probe(experiment_run_id: str, message: str = "SDK communication successful") -> dict:
    """Report exactly one event to VeriQ for an existing run.

    The SDK is imported lazily so the normal worker path does not require
    VeriQ configuration. Failures propagate: this task never pretends an event
    was delivered.
    """
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
