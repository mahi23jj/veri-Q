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

# The target application's own database. The sample tasks do not query it, but
# both workers receive it so real tasks behave exactly as they do normally.
TARGET_DATABASE_URL = os.environ.get("TARGET_DATABASE_URL", "")

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
    task_default_queue=NORMAL_QUEUE,
    task_routes={
        "app.tasks.charge_order": {"queue": NORMAL_QUEUE},
        "app.tasks.veriq_probe": {"queue": VERIQ_QUEUE},
    },
)
