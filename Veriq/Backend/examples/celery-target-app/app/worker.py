"""Celery worker entrypoint.

Both workers use ``celery -A app.worker worker`` so the VeriQ integration is
installed in the parent process before Celery forks. Signal handlers then run in
the executing child process, which is where execution identity is captured.
"""

from app.celery_app import celery_app
from app.veriq_setup import integrate_celery

integrate_celery()

__all__ = ["celery_app"]
