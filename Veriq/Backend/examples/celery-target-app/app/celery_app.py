"""Celery application shared by the normal worker and the VeriQ worker.

Both workers import this module and therefore run identical task code. The only
difference between them is the ``-Q`` queue argument on the command line, so the
VeriQ worker never consumes production traffic and vice versa.
"""

from __future__ import annotations

import os

from celery import Celery

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
NORMAL_QUEUE = os.environ.get("CELERY_NORMAL_QUEUE", "normal")
VERIQ_QUEUE = os.environ.get("VERIQ_QUEUE", "veriq.test")

# The target application's own database. Tasks that persist effects use it, so
# an isolated reliability run can point it at a disposable test database.
TARGET_DATABASE_URL = os.environ.get("TARGET_DATABASE_URL", "")


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


# Acknowledgement policy decides what a worker loss actually does. It is
# configuration, never an assumption: a redelivery test is only meaningful when
# the application acknowledges after execution and rejects on worker loss.
TASK_ACKS_LATE = _flag("CELERY_TASK_ACKS_LATE")
TASK_REJECT_ON_WORKER_LOST = _flag("CELERY_TASK_REJECT_ON_WORKER_LOST")
VISIBILITY_TIMEOUT = int(os.environ.get("CELERY_VISIBILITY_TIMEOUT", "3600"))

celery_app = Celery(
    "celery_target_app",
    broker=CELERY_BROKER_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    timezone="UTC",
    # One task at a time per process keeps execution attribution simple.
    worker_prefetch_multiplier=1,
    task_acks_late=TASK_ACKS_LATE,
    task_reject_on_worker_lost=TASK_REJECT_ON_WORKER_LOST,
    broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT},
    task_default_queue=NORMAL_QUEUE,
    task_routes={
        "app.tasks.charge_order": {"queue": NORMAL_QUEUE},
        "app.tasks.veriq_probe": {"queue": VERIQ_QUEUE},
    },
    # A terminated worker must not keep the test blocked on a result backend.
    task_ignore_result=True,
)
