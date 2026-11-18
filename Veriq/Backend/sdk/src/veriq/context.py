"""Per-execution SDK context.

``contextvars`` is used instead of a module-level dict so concurrent task
executions (threads, greenlets, asyncio) never see each other's execution id.
The value is set in the executing process's ``task_prerun`` handler and cleared
in ``task_postrun``; nothing here is shared across worker processes.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ExecutionContext:
    """One actual task execution attempt inside the current process."""

    execution_id: uuid.UUID
    task_id: str | None
    task_name: str
    started_at: datetime
    worker_instance_id: str
    worker_hostname: str | None
    pid: int
    process_start_identity: str | None
    queue_name: str | None = None
    veriq_run_id: uuid.UUID | None = None
    veriq_operation_id: uuid.UUID | None = None
    # Set once a terminal event (failure/retry) has been reported so
    # ``task_postrun`` cannot append a duplicate success event.
    terminal_sent: bool = False
    # Token returned by ContextVar.set, used to restore the previous context.
    token: Token | None = field(default=None, repr=False)

    def identity_fields(self) -> dict[str, Any]:
        """Stable identity fields repeated on every lifecycle event."""
        return {
            "execution_id": str(self.execution_id),
            "celery_task_id": self.task_id,
            "task_name": self.task_name,
            "worker_instance_id": self.worker_instance_id,
            "worker_hostname": self.worker_hostname,
            "pid": self.pid,
            "process_start_identity": self.process_start_identity,
            "queue_name": self.queue_name,
            "veriq_run_id": str(self.veriq_run_id) if self.veriq_run_id else None,
            "veriq_operation_id": (
                str(self.veriq_operation_id) if self.veriq_operation_id else None
            ),
        }


_EXECUTION_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "veriq_execution_context", default=None
)


def current_execution() -> ExecutionContext | None:
    """The execution context of the calling task, or ``None`` outside a task."""
    return _EXECUTION_CONTEXT.get()


def set_execution(context: ExecutionContext) -> None:
    context.token = _EXECUTION_CONTEXT.set(context)


def clear_execution(context: ExecutionContext | None = None) -> None:
    """Restore the previous context; never raise on mismatched contexts."""
    current = _EXECUTION_CONTEXT.get()
    if context is not None and current is not context:
        return
    token = context.token if context is not None else None
    if token is not None:
        try:
            _EXECUTION_CONTEXT.reset(token)
            return
        except ValueError:
            pass
    _EXECUTION_CONTEXT.set(None)
