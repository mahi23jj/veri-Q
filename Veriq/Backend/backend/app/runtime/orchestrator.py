"""Test Orchestrator: owns the complete reliability test lifecycle.

It coordinates components; it does not implement provisioning, worker control,
fault mechanisms or evaluation itself. Every stage persists its state, so an
interrupted run can be inspected and cleaned up after a backend restart instead
of depending on this thread surviving.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.runtime.lifecycle import TERMINAL_STATES
from app.domain.runtime.recovery import RecoveryPolicy
from app.models.runtime import (
    RunnerEnvironment,
    RunnerWorker,
    TestCaseRun,
)
from app.services import runtime_service
from app.runtime import checkpoint_coordination
from app.runtime.contracts import (
    EnvironmentPlan,
    ProvisionResult,
    RuntimeBackend,
    RuntimeBackendError,
    WorkerSpec,
)
from app.runtime.evaluator import ReliabilityEvaluator
from app.runtime.execution import (
    ExecutionController,
    SubmissionError,
    correlated_executions,
)
from app.runtime.fault_controller import FaultController
from app.runtime.finalizer import Finalizer, environment_to_provision_result
from app.runtime.injectors.base import FaultContext
from app.runtime.injectors.scenario_injectors import INJECTOR_TYPES
from app.runtime.observer import RecoveryObserver
from app.runtime.supervisor import RunnerSupervisor

# Scenarios whose fault must be armed *after* the first message is submitted.
_POST_SUBMISSION_INJECTORS = {"broker_duplicate_submission", "worker_termination"}
_HTTP_PROXY_SCENARIOS = {"dependency_timeout", "successful_operation_lost_response"}
_DATABASE_PROXY_SCENARIOS = {"database_connection_interruption"}


class RunnerInfrastructureError(Exception):
    """VeriQ's own runtime failed; this is never the application's fault."""


class RunCancelled(Exception):
    """The operator cancelled the run."""


class RunTimedOut(Exception):
    """The overall run deadline expired."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OrchestratorSettings:
    provisioning_timeout: int = 180
    worker_startup_timeout: int = 120
    fault_activation_timeout: int = 45
    execution_timeout: int = 120
    recovery_timeout: int = 150
    finalization_timeout: int = 120
    total_timeout: int = 900
    api_base_url: str = "http://host.docker.internal:8000"
    poll_interval: float = 0.5

    @classmethod
    def from_app_settings(cls) -> "OrchestratorSettings":
        return cls(
            provisioning_timeout=settings.RUNNER_PROVISIONING_TIMEOUT_SECONDS,
            worker_startup_timeout=settings.RUNNER_WORKER_STARTUP_TIMEOUT_SECONDS,
            fault_activation_timeout=settings.RUNNER_FAULT_ACTIVATION_TIMEOUT_SECONDS,
            execution_timeout=settings.RUNNER_EXECUTION_TIMEOUT_SECONDS,
            recovery_timeout=settings.RUNNER_RECOVERY_TIMEOUT_SECONDS,
            finalization_timeout=settings.RUNNER_FINALIZATION_TIMEOUT_SECONDS,
            total_timeout=settings.RUNNER_TOTAL_TIMEOUT_SECONDS,
            api_base_url=settings.RUNNER_CALLBACK_BASE_URL,
        )


@dataclass
class TestOrchestrator:
    db: Session
    backend: RuntimeBackend
    executor_factory: Callable[[str], ExecutionController] | None = None
    settings: OrchestratorSettings = field(default_factory=OrchestratorSettings.from_app_settings)

    _executor: ExecutionController | None = field(default=None, init=False)
    _deadline: float = field(default=0.0, init=False)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def execute(self, run_id: uuid.UUID) -> TestCaseRun:
        run = self.db.get(TestCaseRun, run_id)
        if run is None:
            raise RunnerInfrastructureError(f"test case run {run_id} does not exist")
        if run.lifecycle_state in TERMINAL_STATES:
            return run

        self._deadline = time.monotonic() + self.settings.total_timeout
        recorder = runtime_service.RuntimeRecorder(self.db, run)
        supervisor = RunnerSupervisor(backend=self.backend, record=recorder.runtime_event)
        finalizer = Finalizer(
            backend=self.backend, supervisor=supervisor, record=recorder.runtime_event
        )

        controller: FaultController | None = None
        plan: EnvironmentPlan | None = None
        provisioned: ProvisionResult | None = None
        worker: RunnerWorker | None = None
        policy = RecoveryPolicy.from_contract({"recovery": run.recovery_policy or {}})
        runner_failure: str | None = None
        configuration_invalid = False
        cancelled = False
        collected = None

        try:
            self._stage(run, "VALIDATING")
            executable = runtime_service.validate_executable(self.db, run)
            policy = executable.policy
            profile = executable.profile
            plan = runtime_service.build_environment_plan(executable)
            self._guard(run)

            # ----------------------------------------------------------
            self._stage(run, "PROVISIONING")
            environment = RunnerEnvironment(
                test_case_run_id=run.id,
                runtime_type=profile["runtime_type"],
                namespace=plan.namespace,
                provisioning_state="PROVISIONING",
                cleanup_state="PENDING",
                container_refs=[],
                proxy_refs={},
                runtime_config_version="1.0",
            )
            self.db.add(environment)
            self.db.commit()
            self.db.refresh(environment)
            run.environment_id = environment.id
            self.db.commit()
            recorder.runtime_event(
                "ORCHESTRATOR",
                "environment_provisioning",
                {
                    "namespace": plan.namespace,
                    "runtime_type": plan.runtime_type,
                    "network": plan.network_name,
                },
            )
            try:
                provisioned = self.backend.provision(plan)
            except RuntimeBackendError as exc:
                environment.provisioning_state = "FAILED"
                environment.error = str(exc)
                self.db.commit()
                raise RunnerInfrastructureError(str(exc)) from exc
            environment.network_ref = provisioned.network_ref
            environment.container_refs = list(provisioned.containers)
            environment.broker_ref = provisioned.broker_ref
            environment.database_ref = provisioned.database_ref
            environment.proxy_refs = {"detail": provisioned.detail}
            self.db.commit()

            readiness = self.backend.wait_until_ready(
                plan, provisioned, timeout_seconds=self.settings.provisioning_timeout
            )
            environment.readiness = readiness.to_dict()
            if not readiness.ok:
                environment.provisioning_state = "FAILED"
                environment.error = "; ".join(readiness.blockers)
                self.db.commit()
                recorder.runtime_event(
                    "ORCHESTRATOR",
                    "environment_not_ready",
                    {"blockers": list(readiness.blockers)},
                )
                raise RunnerInfrastructureError(
                    "environment readiness failed: " + "; ".join(readiness.blockers)
                )
            environment.provisioning_state = "READY"
            environment.ready_at = _now()
            self.db.commit()
            recorder.runtime_event(
                "ORCHESTRATOR",
                "environment_ready",
                {"checks": [check.to_dict() for check in readiness.checks]},
            )

            # ----------------------------------------------------------
            self._stage(run, "PREPARING_FAULT")
            prepared_detail: dict[str, Any] = {}
            context = FaultContext(
                test_run_id=str(run.id),
                scenario_id=run.scenario_id,
                config=dict(run.configuration.get("scenario_config") or {}),
                trigger_type=run.trigger_type,
                checkpoint_name=run.checkpoint_name,
                operation_id=str(run.id),
                queue_name=plan.worker.queue_name,
                dependency_url=runtime_service.dependency_upstream(
                    run.configuration, profile
                ),
                database_upstream=(
                    _database_upstream(provisioned)
                    if run.scenario_id in _DATABASE_PROXY_SCENARIOS
                    else None
                ),
                advertised_host=str(
                    (profile.get("http") or {}).get(
                        "advertised_host",
                        "127.0.0.1" if plan.runtime_type == "simulated" else "host.docker.internal",
                    )
                ),
                record=recorder.runtime_event,
                wait_for_checkpoint=lambda timeout: self._wait_for_checkpoint(run.id, timeout),
                wait_for_task_running=lambda timeout: self._wait_for_task_running(run, timeout),
                submit_duplicate=lambda count: self._submit_additional(run, plan, count),
                terminate_worker=lambda reason: self._terminate_worker(run, worker, reason),
            )
            controller = FaultController(context=context, recorder=recorder)
            prepared_detail = controller.prepare()
            self._guard(run)

            http_proxy_origin = prepared_detail.get("proxy_origin")
            database_proxy_port = prepared_detail.get("database_proxy_port")

            # ----------------------------------------------------------
            self._stage(run, "STARTING")
            worker = RunnerWorker(
                test_case_run_id=run.id,
                environment_id=environment.id,
                worker_key="primary",
                queue_name=plan.worker.queue_name,
                concurrency=1,
                lifecycle_state="PENDING",
            )
            self.db.add(worker)
            self.db.commit()
            self.db.refresh(worker)

            credential = runtime_service.create_runner_credential(self.db, run)
            worker_env = runtime_service.worker_environment(
                plan,
                provisioned=provisioned,
                api_base_url=self.settings.api_base_url,
                api_key=credential,
                http_proxy_origin=http_proxy_origin,
                database_proxy_port=database_proxy_port,
            )
            try:
                supervisor.start_worker(
                    self.db,
                    worker=worker,
                    plan=plan,
                    provisioned=provisioned,
                    env=worker_env,
                )
            except RuntimeBackendError as exc:
                raise RunnerInfrastructureError(
                    f"dedicated worker failed to start: {exc}"
                ) from exc

            ready_report = supervisor.wait_for_worker_ready(
                self.db,
                worker=worker,
                plan=plan,
                timeout_seconds=self.settings.worker_startup_timeout,
                target_app_id=run.target_app_id,
            )
            if not ready_report.ready:
                raise RunnerInfrastructureError(
                    f"dedicated worker did not become ready: {ready_report.check.detail}"
                )
            worker.lifecycle_state = "RUNNING"
            self.db.commit()
            self._guard(run)

            # Arm automatic infrastructure faults *before* the first request,
            # so the very first attempt already experiences the fault.
            injector_type = INJECTOR_TYPES.get(run.scenario_id, "")
            if run.trigger_type != "checkpoint" and injector_type not in _POST_SUBMISSION_INJECTORS:
                controller.activate("automatic_trigger")

            # ----------------------------------------------------------
            self._stage(run, "RUNNING")
            broker_url = (
                provisioned.detail.get("broker_submit_ref")
                if provisioned.detail
                else None
            ) or provisioned.broker_ref or ""
            self._executor = (
                self.executor_factory(broker_url)
                if self.executor_factory is not None
                else ExecutionController(broker_url=broker_url)
            )
            if run.trigger_type == "checkpoint":
                checkpoint_coordination.register(
                    str(run.id), self._checkpoint_activator(controller, run)
                )
            payload = dict(run.configuration.get("test_input") or {})
            if http_proxy_origin:
                payload = runtime_service.input_with_proxy(
                    run.configuration, profile, str(http_proxy_origin)
                )
            submission = self._submit(run, plan, payload, task_id=None)
            recorder.runtime_event(
                "BROKER",
                "message_submitted",
                {
                    "task_id": submission.task_id,
                    "queue": submission.queue,
                    "logical_job_id": str(run.logical_job_id),
                    "attempt": 1,
                    "correlation": "veriq_operation_id",
                },
            )

            # ----------------------------------------------------------
            self._stage(run, "INJECTING")
            if run.trigger_type == "checkpoint":
                matched = controller.wait_for_trigger(self.settings.fault_activation_timeout)
                if matched:
                    controller.persist_pending_activation()
            elif injector_type in _POST_SUBMISSION_INJECTORS:
                fired = controller.wait_for_trigger(self.settings.execution_timeout)
                if not fired:
                    recorder.runtime_event(
                        "ORCHESTRATOR",
                        "fault_trigger_not_reached",
                        {"scenario_id": run.scenario_id},
                    )
                else:
                    controller.activate("execution_trigger")

            # ----------------------------------------------------------
            self._stage(run, "OBSERVING_RECOVERY")
            # A terminated process cannot consume a redelivered message. Recovery
            # is only observable if a replacement worker runs the same code, so
            # the supervisor starts one before the observation window opens.
            self.db.refresh(worker)
            if worker.lifecycle_state in ("TERMINATED", "FAILED"):
                replacement = RunnerWorker(
                    test_case_run_id=run.id,
                    environment_id=environment.id,
                    worker_key="recovery",
                    queue_name=plan.worker.queue_name,
                    concurrency=1,
                    lifecycle_state="PENDING",
                )
                self.db.add(replacement)
                self.db.commit()
                self.db.refresh(replacement)
                try:
                    supervisor.start_worker(
                        self.db,
                        worker=replacement,
                        plan=plan,
                        provisioned=provisioned,
                        env=worker_env,
                    )
                    replacement_ready = supervisor.wait_for_worker_ready(
                        self.db,
                        worker=replacement,
                        plan=plan,
                        timeout_seconds=self.settings.worker_startup_timeout,
                        target_app_id=run.target_app_id,
                    )
                    if replacement_ready.ready:
                        replacement.lifecycle_state = "RUNNING"
                        self.db.commit()
                    else:
                        recorder.runtime_event(
                            "RUNNER",
                            "recovery_worker_not_ready",
                            {"detail": replacement_ready.check.detail},
                        )
                except RuntimeBackendError as exc:
                    recorder.runtime_event(
                        "RUNNER", "recovery_worker_failed", {"error": str(exc)}
                    )
            self._observe(run, policy)
            if controller.activated:
                controller.deactivate("observation_window_closed")

            self._guard(run)

            # ----------------------------------------------------------
            self._stage(run, "EVALUATING")
            collected = RecoveryObserver(self.db).collect(
                run,
                policy=policy,
                fault_activated=controller.activated,
                fault_activation_at=controller.activation_at,
                task_submitted=True,
            )
            runtime_service.persist_recovery(self.db, run, collected.result)
            verdict = ReliabilityEvaluator().evaluate(
                policy=policy,
                observation=collected.result,
                scenario_id=run.scenario_id,
                runner_failure=None,
            )
            runtime_service.set_verdict(self.db, run, verdict=verdict.verdict, detail=verdict.to_dict())
            recorder.runtime_event(
                "OBSERVER",
                "evaluation_completed",
                {
                    "verdict": verdict.verdict,
                    "attempts": collected.result.attempt_count,
                    "retries": collected.result.retry_request_count,
                },
            )

        except runtime_service.RunNotExecutableError as exc:
            # The approved case can no longer be executed as approved. This is
            # not a runner outage and not an application failure: the intended
            # test never happened, so the verdict is INVALID_RUN.
            configuration_invalid = True
            run.error_message = "; ".join(issue["message"] for issue in exc.issues)
            self.db.commit()
            runtime_service.set_verdict(
                self.db,
                run,
                verdict="INVALID_RUN",
                detail={
                    "verdict": "INVALID_RUN",
                    "reasons": list(exc.issues),
                    "scope": "execution_recovery_only",
                },
            )
            recorder.runtime_event(
                "ORCHESTRATOR",
                "configuration_not_executable",
                {"issues": list(exc.issues)},
            )
        except RunCancelled:
            cancelled = True
            runner_failure = None
            collected = self._best_effort_observation(run, policy, controller)
            runtime_service.set_verdict(
                self.db,
                run,
                verdict="INCONCLUSIVE",
                detail={
                    "verdict": "INCONCLUSIVE",
                    "reasons": [
                        {
                            "code": "RUN_CANCELLED",
                            "message": "The run was cancelled before a verdict could be reached.",
                        }
                    ],
                },
            )
            recorder.runtime_event("ORCHESTRATOR", "run_cancelled", {})
        except (RunnerInfrastructureError, RunTimedOut, SubmissionError, RuntimeBackendError) as exc:
            runner_failure = f"{type(exc).__name__}: {exc}"
            collected = self._best_effort_observation(run, policy, controller)
            verdict = ReliabilityEvaluator().evaluate(
                policy=policy,
                observation=(
                    collected.result if collected is not None else _empty_observation(policy)
                ),
                scenario_id=run.scenario_id,
                runner_failure=runner_failure,
            )
            run.error_message = runner_failure
            self.db.commit()
            runtime_service.set_verdict(self.db, run, verdict=verdict.verdict, detail=verdict.to_dict())
            recorder.runtime_event(
                "ORCHESTRATOR", "run_failed", {"error": runner_failure}
            )
        except Exception as exc:  # unexpected orchestrator bug: never lose evidence
            runner_failure = f"{type(exc).__name__}: {exc}"
            self.db.rollback()
            run = self.db.get(TestCaseRun, run_id)
            if run is not None and run.lifecycle_state not in TERMINAL_STATES:
                run.error_message = runner_failure
                self.db.commit()
                try:
                    runtime_service.set_verdict(
                        self.db,
                        run,
                        verdict="ERROR",
                        detail={
                            "verdict": "ERROR",
                            "reasons": [
                                {
                                    "code": "ORCHESTRATOR_FAILURE",
                                    "message": f"VeriQ could not complete the run: {runner_failure}",
                                }
                            ],
                        },
                    )
                except Exception:  # pragma: no cover - best effort
                    self.db.rollback()
        finally:
            checkpoint_coordination.unregister(str(run_id))
            final_state = (
                "CANCELLED"
                if cancelled
                else (
                    "FAILED"
                    if (runner_failure or configuration_invalid)
                    else "COMPLETED"
                )
            )
            if run is not None and run.lifecycle_state not in TERMINAL_STATES:
                try:
                    self._stage(run, "FINALIZING")
                except Exception:  # pragma: no cover - defensive
                    self.db.rollback()
            self._cleanup(
                run_id,
                finalizer=finalizer,
                controller=controller,
                plan=plan,
                provisioned=provisioned,
                final_state=final_state,
            )
            if self._executor is not None:
                self._executor.close()
                self._executor = None
            if controller is not None:
                controller.close()

        refreshed = self.db.get(TestCaseRun, run_id)
        return refreshed if refreshed is not None else run

    # ------------------------------------------------------------------
    # Stage helpers
    # ------------------------------------------------------------------
    def _stage(self, run: TestCaseRun, state: str) -> None:
        runtime_service.set_lifecycle(self.db, run, state)

    def _guard(self, run: TestCaseRun) -> None:
        self.db.refresh(run)
        if run.cancel_requested_at is not None:
            raise RunCancelled()
        if time.monotonic() > self._deadline:
            raise RunTimedOut("overall run deadline exceeded")

    def _submit(
        self,
        run: TestCaseRun,
        plan: EnvironmentPlan,
        payload: dict[str, Any],
        *,
        task_id: str | None,
    ):
        if self._executor is None:
            raise RunnerInfrastructureError("execution controller is not initialised")
        submission = self._executor.submit(
            task_name=run.configuration["task_name"],
            payload=payload,
            queue=plan.worker.queue_name,
            operation_id=str(run.id),
            logical_job_id=str(run.logical_job_id),
            task_id=task_id,
        )
        identifiers = list(run.celery_task_ids or [])
        identifiers.append(submission.task_id)
        run.celery_task_ids = identifiers
        self.db.commit()
        return submission

    def _submit_additional(
        self, run: TestCaseRun, plan: EnvironmentPlan, count: int
    ) -> list[str]:
        payload = dict(run.configuration.get("test_input") or {})
        profile = run.runtime_profile_snapshot or {}
        task_ids: list[str] = []
        for _index in range(max(0, count)):
            submission = self._submit(run, plan, payload, task_id=None)
            task_ids.append(submission.task_id)
        return task_ids

    def _terminate_worker(
        self, run: TestCaseRun, worker: RunnerWorker | None, reason: str
    ) -> dict[str, Any]:
        if worker is None:
            raise RunnerInfrastructureError("no dedicated worker to terminate")
        recorder = runtime_service.RuntimeRecorder(self.db, run)
        supervisor = RunnerSupervisor(
            backend=self.backend, record=recorder.runtime_event
        )
        result = supervisor.terminate_worker(self.db, worker=worker, reason=reason)
        return {
            "terminated": result.terminated,
            "detail": result.detail,
            "check": result.check.to_dict(),
        }

    def _wait_for_task_running(self, run: TestCaseRun, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            # Start a fresh transaction so telemetry committed by the API is seen.
            self.db.rollback()
            for execution in correlated_executions(
                self.db, target_app_id=run.target_app_id, test_run_id=run.id
            ):
                if execution.status == "RUNNING":
                    return True
            if self._cancelled(run):
                raise RunCancelled()
            time.sleep(self.settings.poll_interval)
        return False

    def _checkpoint_activator(self, controller: FaultController, run: TestCaseRun):
        expected = run.checkpoint_name

        def activate(checkpoint_name: str, detail: dict[str, Any]) -> bool:
            if expected is not None and checkpoint_name != expected:
                return False
            if controller.activated:
                return False
            # Activation happens while the SDK's checkpoint request is being
            # answered; the runner persists the event afterwards.
            controller.activate(f"checkpoint:{checkpoint_name}", record=False)
            return True

        return activate

    def _wait_for_checkpoint(self, run_id: uuid.UUID, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            self.db.rollback()
            run = self.db.get(TestCaseRun, run_id)
            if run is not None and run.cancel_requested_at is not None:
                raise RunCancelled()
            if self._acknowledged_waits(run_id) or self._activation_recorded(run_id):
                return True
            time.sleep(0.05)
        return False

    def _acknowledged_waits(self, run_id: uuid.UUID) -> bool:
        from sqlalchemy import select

        from app.models.runtime import CheckpointWait

        row = self.db.scalar(
            select(CheckpointWait).where(
                CheckpointWait.test_case_run_id == run_id,
                CheckpointWait.state == "ACKNOWLEDGED",
            )
        )
        return row is not None

    def _activation_recorded(self, run_id: uuid.UUID) -> bool:
        from sqlalchemy import select

        from app.models.runtime import FaultEvent

        row = self.db.scalar(
            select(FaultEvent).where(
                FaultEvent.test_case_run_id == run_id, FaultEvent.state == "ACTIVE"
            )
        )
        return row is not None

    def _cancelled(self, run: TestCaseRun) -> bool:
        self.db.refresh(run)
        return run.cancel_requested_at is not None

    def _observe(self, run: TestCaseRun, policy: RecoveryPolicy) -> None:
        """Wait for the observed execution to settle, bounded by every deadline."""
        started = time.monotonic()
        execution_deadline = started + self.settings.execution_timeout
        recovery_deadline: float | None = None
        terminal_seen_at: float | None = None
        timeout_recorded = False

        while True:
            self.db.rollback()
            if self._cancelled(run):
                raise RunCancelled()
            if time.monotonic() > self._deadline:
                raise RunTimedOut("overall run deadline exceeded")

            executions = correlated_executions(
                self.db, target_app_id=run.target_app_id, test_run_id=run.id
            )
            if executions and recovery_deadline is None:
                window = min(policy.recovery_deadline_seconds, self.settings.recovery_timeout)
                recovery_deadline = time.monotonic() + window

            if executions and all(execution.finished_at is not None for execution in executions):
                if terminal_seen_at is None:
                    terminal_seen_at = time.monotonic()
                elif time.monotonic() - terminal_seen_at >= policy.settle_seconds:
                    runtime_service.record_runtime_event(
                        self.db,
                        run,
                        source="OBSERVER",
                        event_type="execution_settled",
                        payload={
                            "attempts": [
                                {"status": execution.status} for execution in executions
                            ]
                        },
                    )
                    self.db.commit()
                    return
            else:
                terminal_seen_at = None

            if not executions and time.monotonic() > execution_deadline:
                if not timeout_recorded:
                    runtime_service.record_runtime_event(
                        self.db,
                        run,
                        source="OBSERVER",
                        event_type="execution_timeout",
                        payload={"reason": "no execution attempt was observed"},
                    )
                    self.db.commit()
                    timeout_recorded = True
                return

            if recovery_deadline is not None and time.monotonic() > recovery_deadline:
                if not timeout_recorded:
                    runtime_service.record_runtime_event(
                        self.db,
                        run,
                        source="OBSERVER",
                        event_type="recovery_timeout",
                        payload={
                            "reason": "recovery deadline reached before the execution settled",
                            "attempts": len(executions),
                        },
                    )
                    self.db.commit()
                    timeout_recorded = True
                return

            time.sleep(self.settings.poll_interval)

    def _best_effort_observation(
        self,
        run: TestCaseRun,
        policy: RecoveryPolicy,
        controller: FaultController | None,
    ):
        try:
            self.db.rollback()
            return RecoveryObserver(self.db).collect(
                run,
                policy=policy,
                fault_activated=bool(controller and controller.activated),
                fault_activation_at=controller.activation_at if controller else None,
                task_submitted=bool(run.celery_task_ids),
            )
        except Exception:  # pragma: no cover - evidence must not block cleanup
            self.db.rollback()
            return None

    def _cleanup(
        self,
        run_id: uuid.UUID,
        *,
        finalizer: Finalizer,
        controller: FaultController | None,
        plan: EnvironmentPlan | None,
        provisioned: ProvisionResult | None,
        final_state: str,
    ) -> None:
        try:
            self.db.rollback()
            run = self.db.get(TestCaseRun, run_id)
            if run is None:
                return
            environment = runtime_service.get_environment(self.db, run)
            if provisioned is None and environment is not None and environment.container_refs:
                provisioned = environment_to_provision_result(environment)
            if plan is None and environment is not None:
                plan = EnvironmentPlan(
                    test_run_id=str(run.id),
                    target_app_id=str(run.target_app_id),
                    namespace=environment.namespace,
                    runtime_type=environment.runtime_type,
                    network_name=environment.network_ref or f"{environment.namespace}-net",
                    worker=WorkerSpec(
                        image=str((run.runtime_profile_snapshot or {}).get("image") or "unknown"),
                        command=tuple(
                            (run.runtime_profile_snapshot or {}).get("worker_command") or ()
                        ),
                        queue_name=str(environment.namespace),
                    ),
                    broker=None,
                    database=None,
                )
            finalizer.finalize(
                self.db,
                run=run,
                final_state=final_state,
                reason="completed" if final_state == "COMPLETED" else final_state.lower(),
                controller=controller,
                plan=plan,
                provisioned=provisioned,
            )
        except Exception:
            # Cleanup failures are recorded on the environment where possible;
            # they never erase the verdict.
            try:
                self.db.rollback()
            except Exception:  # pragma: no cover
                pass


def _database_upstream(provisioned: ProvisionResult | None) -> tuple[str, int] | None:
    if provisioned is None:
        return None
    target = provisioned.detail.get("database_readiness")
    if not target:
        return None
    return str(target["host"]), int(target["port"])


def _empty_observation(policy: RecoveryPolicy):
    from app.domain.runtime.recovery import derive_observation

    return derive_observation(
        policy=policy,
        attempts=[],
        retry_request_count=0,
        fault_activated=False,
        task_submitted=False,
    )


__all__ = [
    "OrchestratorSettings",
    "RunCancelled",
    "RunTimedOut",
    "RunnerInfrastructureError",
    "TestOrchestrator",
]
