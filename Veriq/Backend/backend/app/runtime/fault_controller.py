"""Fault Controller: coordinates injectors, records what actually happened.

The controller does not implement any failure mechanism. It resolves the
injector for the selected scenario, validates its configuration, prepares it,
activates it at the selected trigger, releases it, and persists a FaultEvent for
every transition.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.runtime.injectors.base import (
    FaultContext,
    FaultInjector,
    InjectorError,
    TRIGGER_CHECKPOINT,
)
from app.runtime.injectors.scenario_injectors import build_injector


class FaultRecorder(Protocol):
    def fault_event(
        self,
        *,
        state: str,
        injector_type: str,
        trigger_type: str,
        trigger_ref: str | None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
        activation_at: datetime | None = None,
        deactivation_at: datetime | None = None,
    ) -> None: ...

    def runtime_event(self, source: str, event_type: str, payload: dict[str, Any]) -> None: ...


@dataclass
class FaultController:
    context: FaultContext
    recorder: FaultRecorder
    _injector: FaultInjector | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _prepared: bool = field(default=False, init=False)
    _activated: bool = field(default=False, init=False)
    _released: bool = field(default=False, init=False)
    _activation_at: datetime | None = field(default=None, init=False)
    _detail: dict[str, Any] = field(default_factory=dict, init=False)
    _pending_record: bool = field(default=False, init=False)

    # ------------------------------------------------------------------
    @property
    def injector(self) -> FaultInjector:
        if self._injector is None:
            raise InjectorError("fault controller has no prepared injector")
        return self._injector

    @property
    def activated(self) -> bool:
        with self._lock:
            return self._activated

    @property
    def activation_at(self) -> datetime | None:
        with self._lock:
            return self._activation_at

    @property
    def injector_type(self) -> str:
        return getattr(self._injector, "injector_type", "unknown")

    # ------------------------------------------------------------------
    def prepare(self) -> dict[str, Any]:
        """Resolve, validate and prepare the injector; never activates it."""
        injector = build_injector(self.context.scenario_id)
        problems = injector.validate(self.context)
        if problems:
            self.recorder.fault_event(
                state="FAILED",
                injector_type=injector.injector_type,
                trigger_type=self.context.trigger_type,
                trigger_ref=self.context.checkpoint_name,
                error="; ".join(problems),
            )
            raise InjectorError("; ".join(problems))
        self._injector = injector
        self.recorder.fault_event(
            state="PREPARING",
            injector_type=injector.injector_type,
            trigger_type=self.context.trigger_type,
            trigger_ref=self.context.checkpoint_name,
        )
        try:
            detail = injector.prepare(self.context)
        except Exception as exc:
            self.recorder.fault_event(
                state="FAILED",
                injector_type=injector.injector_type,
                trigger_type=self.context.trigger_type,
                trigger_ref=self.context.checkpoint_name,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise InjectorError(f"injector preparation failed: {exc}") from exc
        self._prepared = True
        self._detail = dict(detail)
        self.recorder.fault_event(
            state="ARMED",
            injector_type=injector.injector_type,
            trigger_type=self.context.trigger_type,
            trigger_ref=self.context.checkpoint_name,
            detail=detail,
        )
        return detail

    def wait_for_trigger(self, timeout_seconds: float) -> bool:
        """Wait for the configured trigger.

        Automatic infrastructure faults fire immediately; checkpoint triggers
        wait for the coordinated checkpoint (bounded); worker termination waits
        for the task to be running.
        """
        if self._injector is None:
            raise InjectorError("fault controller was not prepared")
        if self.context.trigger_type == TRIGGER_CHECKPOINT:
            try:
                matched = self._injector.wait_for_trigger(self.context, timeout_seconds)
            except InjectorError as exc:
                self.recorder.fault_event(
                    state="SKIPPED",
                    injector_type=self.injector_type,
                    trigger_type=self.context.trigger_type,
                    trigger_ref=self.context.checkpoint_name,
                    detail={"matched": False, "checkpoint": self.context.checkpoint_name},
                    error=str(exc),
                )
                return False
            self.recorder.fault_event(
                state="TRIGGERED" if matched else "SKIPPED",
                injector_type=self.injector_type,
                trigger_type=self.context.trigger_type,
                trigger_ref=self.context.checkpoint_name,
                detail={
                    "matched": matched,
                    "checkpoint": self.context.checkpoint_name,
                    "timeout_seconds": timeout_seconds,
                },
                error=None if matched else "checkpoint was not observed before the timeout",
            )
            return matched
        return True

    def activate(self, reason: str = "trigger", *, record: bool = True) -> dict[str, Any]:
        """Activate the fault. Idempotent: a second call reuses the first result.

        ``record=False`` is used by the checkpoint coordination path: activation
        must happen while the SDK's checkpoint request is being answered, and the
        observation session must stay the only database writer. The runner then
        calls :meth:`persist_pending_activation`.
        """
        with self._lock:
            if self._activated:
                return {**self._detail, "already_active": True}
            if self._injector is None:
                raise InjectorError("fault controller was not prepared")
            try:
                detail = self._injector.activate(self.context)
            except Exception as exc:
                self.recorder.fault_event(
                    state="FAILED",
                    injector_type=self.injector_type,
                    trigger_type=self.context.trigger_type,
                    trigger_ref=self.context.checkpoint_name,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise InjectorError(f"fault activation failed: {exc}") from exc
            self._activated = True
            self._activation_at = datetime.now(timezone.utc)
            self._detail = {**self._detail, **dict(detail or {}), "activation_reason": reason}
            self._pending_record = not record
            if record:
                self._write_activation_event()
            return self._detail

    def persist_pending_activation(self) -> None:
        """Persist an activation that happened on the checkpoint-report path."""
        with self._lock:
            if self._pending_record:
                self._write_activation_event()
                self._pending_record = False

    def _write_activation_event(self) -> None:
        self.recorder.fault_event(
            state="ACTIVE",
            injector_type=self.injector_type,
            trigger_type=self.context.trigger_type,
            trigger_ref=self.context.checkpoint_name,
            detail=self._detail,
            activation_at=self._activation_at,
        )

    def deactivate(self, reason: str = "finalize") -> dict[str, Any]:
        with self._lock:
            if self._injector is None or self._released:
                return {"deactivated": False, "reason": "nothing to release"}
            try:
                detail = self._injector.deactivate(self.context) or {}
            except Exception as exc:
                self.recorder.fault_event(
                    state="FAILED",
                    injector_type=self.injector_type,
                    trigger_type=self.context.trigger_type,
                    trigger_ref=self.context.checkpoint_name,
                    error=f"release failed: {exc}",
                )
                return {"deactivated": False, "error": str(exc)}
            self._released = True
            self.recorder.fault_event(
                state="RELEASED",
                injector_type=self.injector_type,
                trigger_type=self.context.trigger_type,
                trigger_ref=self.context.checkpoint_name,
                detail={**dict(detail), "release_reason": reason},
                activation_at=self._activation_at,
                deactivation_at=datetime.now(timezone.utc),
            )
            return detail

    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scenario_id": self.context.scenario_id,
            "trigger_type": self.context.trigger_type,
            "checkpoint": self.context.checkpoint_name,
            "prepared": self._prepared,
            "activated": self._activated,
            "released": self._released,
            "activation_at": self._activation_at.isoformat() if self._activation_at else None,
        }
        if self._injector is not None:
            payload["injector"] = self._injector.status()
        return payload

    def close(self) -> None:
        if self._injector is not None:
            try:
                self._injector.close()
            except Exception:  # pragma: no cover - teardown best effort
                pass


def monotonic() -> float:
    return time.monotonic()


__all__ = ["FaultController", "FaultRecorder", "InjectorError", "monotonic"]
