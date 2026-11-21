"""Finalization and cleanup.

Runs for every terminal path and is idempotent. Order matters: evidence is
already persisted before resources disappear, faults are released first, then
the worker, then the environment.

A cleanup failure is recorded but never overwrites the reliability verdict: the
result stays readable even when a container could not be removed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import (
    RunnerCredential,
    RunnerEnvironment,
    RunnerWorker,
    TestCaseRun,
)
from app.runtime.contracts import (
    EnvironmentPlan,
    ProvisionResult,
    RuntimeBackend,
)
from app.runtime.supervisor import RunnerSupervisor

RecordFn = Callable[[str, str, dict[str, Any]], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FinalizationOutcome:
    lifecycle_state: str
    errors: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.errors


@dataclass
class Finalizer:
    backend: RuntimeBackend
    supervisor: RunnerSupervisor
    record: RecordFn | None = None

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.record is not None:
            self.record("CLEANUP", event_type, payload)

    # ------------------------------------------------------------------
    def finalize(
        self,
        db: Session,
        *,
        run: TestCaseRun,
        final_state: str,
        reason: str,
        controller: Any | None = None,
        plan: EnvironmentPlan | None = None,
        provisioned: ProvisionResult | None = None,
    ) -> FinalizationOutcome:
        errors: list[str] = []
        removed: list[str] = []
        skipped: list[str] = []

        environment = db.scalar(
            select(RunnerEnvironment).where(RunnerEnvironment.test_case_run_id == run.id)
        )
        workers = list(
            db.scalars(
                select(RunnerWorker)
                .where(RunnerWorker.test_case_run_id == run.id)
                .order_by(RunnerWorker.created_at)
            ).all()
        )

        # 1. Stop accepting new actions and release the fault.
        if controller is not None:
            try:
                controller.deactivate(reason=f"finalize:{reason}")
            except Exception as exc:
                errors.append(f"fault release: {exc}")

        # 2. Stop the dedicated worker(s).
        for worker in workers:
            if worker.lifecycle_state in ("STOPPED", "TERMINATED"):
                skipped.append(f"worker:{worker.worker_key}")
                continue
            try:
                self.supervisor.stop_worker(db, worker=worker)
                removed.append(f"worker:{worker.worker_key}")
            except Exception as exc:
                errors.append(f"stop worker {worker.worker_key}: {exc}")

        # 3. Stop the test dependencies, then 4. remove the environment.
        if environment is not None and plan is not None and provisioned is not None:
            if environment.cleanup_state == "CLEANED":
                skipped.append(f"environment:{environment.namespace}")
            else:
                environment.cleanup_state = "CLEANING"
                db.commit()
                try:
                    self.backend.stop_environment(plan, provisioned)
                except Exception as exc:
                    errors.append(f"stop environment: {exc}")
                try:
                    cleanup = self.backend.cleanup_environment(plan, provisioned)
                    removed.extend(cleanup.removed)
                    errors.extend(cleanup.errors)
                except Exception as exc:
                    errors.append(f"cleanup environment: {exc}")
                environment.cleanup_state = "CLEANED" if not errors else "FAILED"
                environment.cleanup_error = "; ".join(errors) or None
                environment.cleaned_at = _now() if not errors else None
                db.commit()
        elif environment is not None:
            # Nothing was provisioned (failure before/inside provisioning):
            # reconstruct nothing, just record that there is nothing to remove.
            environment.cleanup_state = "CLEANED" if not environment.container_refs else "FAILED"
            environment.cleanup_error = (
                None
                if not environment.container_refs
                else "runtime plan unavailable: containers may remain"
            )
            db.commit()
            skipped.append(f"environment:{environment.namespace}")

        # 5. Revoke the run-scoped SDK credential.
        credentials = list(
            db.scalars(
                select(RunnerCredential).where(RunnerCredential.test_case_run_id == run.id)
            ).all()
        )
        for credential in credentials:
            credential.revoked_at = credential.revoked_at or _now()
        db.commit()

        # 6. Persist the final lifecycle state without touching the verdict.
        run.lifecycle_state = final_state
        run.finished_at = run.finished_at or _now()
        if errors:
            run.error_message = (run.error_message + " | " if run.error_message else "") + (
                "cleanup: " + "; ".join(errors)
            )
        db.commit()

        self._emit(
            "finalized",
            {
                "reason": reason,
                "lifecycle_state": final_state,
                "verdict": run.verdict,
                "errors": errors,
                "removed": removed,
            },
        )
        return FinalizationOutcome(
            lifecycle_state=final_state,
            errors=tuple(errors),
            removed=tuple(removed),
            skipped=tuple(skipped),
        )

    # ------------------------------------------------------------------
    def recover_orphaned_environment(
        self,
        db: Session,
        *,
        environment: RunnerEnvironment,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
    ) -> FinalizationOutcome:
        """Clean an environment left behind by an interrupted runner."""
        return self.finalize(
            db,
            run=db.get(TestCaseRun, environment.test_case_run_id),
            final_state="CANCELLED",
            reason="recovered_after_restart",
            plan=plan,
            provisioned=provisioned,
        )


def environment_to_provision_result(environment: RunnerEnvironment) -> ProvisionResult:
    """Reconstruct enough state to clean up after a backend restart."""
    containers = tuple(environment.container_refs or [])
    return ProvisionResult(
        network_ref=environment.network_ref,
        containers=containers,
        broker_ref=environment.broker_ref,
        database_ref=environment.database_ref,
        detail=dict((environment.proxy_refs or {}).get("detail") or {}),
    )


__all__ = ["FinalizationOutcome", "Finalizer", "environment_to_provision_result"]


def missing_environment_error(environment_id: uuid.UUID | None) -> str | None:
    if environment_id is None:
        return "no environment was provisioned"
    return None
