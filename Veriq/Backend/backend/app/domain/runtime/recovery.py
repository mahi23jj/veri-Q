"""Deterministic reliability evaluation from observed evidence.

Nothing here decides whether a *business* effect was correct: the MVP judges
execution-level recovery only (attempts, retries, terminal state, deadline).

Two ideas are kept strictly apart:

* a retry *request* is not a retry *attempt*;
* a configured fault is not an activated fault.

A verdict is therefore derived only from evidence that was actually observed and
persisted, with its authoritative source recorded alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_INVALID_RUN = "INVALID_RUN"
VERDICT_ERROR = "ERROR"

TERMINAL_SUCCESS = "SUCCEEDED"
TERMINAL_FAILURE = "FAILED"
TERMINAL_ANY = "ANY"

SOURCE_SDK = "SDK"
SOURCE_RUNNER = "RUNNER"
SOURCE_INJECTOR = "INJECTOR"
SOURCE_BROKER = "BROKER"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RECOVERY_DEADLINE_SECONDS = 120
DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS = 60
DEFAULT_SETTLE_SECONDS = 3
MAX_ATTEMPTS_LIMIT = 20
MAX_DEADLINE_SECONDS = 3600


def _positive_int(value: Any, default: int, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if value <= 0 or value > maximum:
        return default
    return value


@dataclass(frozen=True)
class RecoveryPolicy:
    """What "recovered" means for one test case.

    Derived from the task test contract (``recovery`` block) and frozen into the
    plan revision, so editing the contract later cannot silently change what a
    past verdict meant.
    """

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    recovery_deadline_seconds: int = DEFAULT_RECOVERY_DEADLINE_SECONDS
    per_attempt_timeout_seconds: int = DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS
    expected_terminal_state: str = TERMINAL_SUCCESS
    expect_retry: bool | None = None
    expect_redelivery: bool | None = None
    settle_seconds: int = DEFAULT_SETTLE_SECONDS

    @classmethod
    def from_contract(cls, payload: Mapping[str, Any] | None) -> "RecoveryPolicy":
        """Read ``payload['recovery']``; unknown or invalid values fall back."""
        block: Mapping[str, Any] = {}
        if isinstance(payload, Mapping):
            candidate = payload.get("recovery")
            if isinstance(candidate, Mapping):
                block = candidate
        expected = block.get("expected_terminal_state")
        if expected not in (TERMINAL_SUCCESS, TERMINAL_FAILURE, TERMINAL_ANY):
            expected = TERMINAL_SUCCESS
        return cls(
            max_attempts=_positive_int(
                block.get("max_attempts"), DEFAULT_MAX_ATTEMPTS, maximum=MAX_ATTEMPTS_LIMIT
            ),
            recovery_deadline_seconds=_positive_int(
                block.get("recovery_deadline_seconds"),
                DEFAULT_RECOVERY_DEADLINE_SECONDS,
                maximum=MAX_DEADLINE_SECONDS,
            ),
            per_attempt_timeout_seconds=_positive_int(
                block.get("per_attempt_timeout_seconds"),
                DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS,
                maximum=MAX_DEADLINE_SECONDS,
            ),
            expected_terminal_state=expected,
            expect_retry=block.get("expect_retry") if isinstance(block.get("expect_retry"), bool) else None,
            expect_redelivery=(
                block.get("expect_redelivery")
                if isinstance(block.get("expect_redelivery"), bool)
                else None
            ),
            settle_seconds=_positive_int(
                block.get("settle_seconds"), DEFAULT_SETTLE_SECONDS, maximum=120
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "recovery_deadline_seconds": self.recovery_deadline_seconds,
            "per_attempt_timeout_seconds": self.per_attempt_timeout_seconds,
            "expected_terminal_state": self.expected_terminal_state,
            "expect_retry": self.expect_retry,
            "expect_redelivery": self.expect_redelivery,
            "settle_seconds": self.settle_seconds,
        }

    @property
    def recovery_deadline(self) -> timedelta:
        return timedelta(seconds=self.recovery_deadline_seconds)


@dataclass(frozen=True)
class EvidenceRecord:
    """One observed fact with the source that owns it."""

    source: str
    event_type: str
    occurred_at: datetime
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class AttemptView:
    """One observed execution attempt (derived from persisted telemetry)."""

    index: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    retry_requested: bool = False


@dataclass(frozen=True)
class ObservationResult:
    attempt_count: int
    retry_request_count: int
    subsequent_attempt_count: int
    fault_activated: bool
    recovery_duration_ms: int | None
    final_execution_state: str | None
    evidence_complete: bool
    missing_evidence: tuple[str, ...]
    observation: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_count": self.attempt_count,
            "retry_request_count": self.retry_request_count,
            "subsequent_attempt_count": self.subsequent_attempt_count,
            "fault_activated": self.fault_activated,
            "recovery_duration_ms": self.recovery_duration_ms,
            "final_execution_state": self.final_execution_state,
            "evidence_complete": self.evidence_complete,
            "missing_evidence": list(self.missing_evidence),
            "observation": dict(self.observation),
            "evidence": [dict(item) for item in self.evidence],
        }


def _seconds_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def derive_observation(
    *,
    policy: RecoveryPolicy,
    attempts: Sequence[AttemptView],
    retry_request_count: int,
    fault_activated: bool,
    evidence: Iterable[EvidenceRecord] = (),
    task_submitted: bool = False,
    fault_activation_at: datetime | None = None,
    extra_missing: Sequence[str] = (),
) -> ObservationResult:
    """Turn observed attempts into recovery measurements.

    Missing evidence is recorded, never assumed away: an absent terminal event
    stays absent so the evaluator can return INCONCLUSIVE.
    """
    ordered = sorted(attempts, key=lambda attempt: (attempt.started_at, attempt.index))
    attempt_count = len(ordered)
    missing: list[str] = list(dict.fromkeys(extra_missing))

    if task_submitted and attempt_count == 0:
        missing.append("TASK_ATTEMPT_NOT_OBSERVED")
    if attempt_count and ordered[-1].finished_at is None:
        missing.append("TERMINAL_EXECUTION_EVENT_MISSING")
    if attempt_count == 0 and not task_submitted:
        missing.append("TASK_NOT_SUBMITTED")

    finished_at = ordered[-1].finished_at if ordered else None
    final_state = ordered[-1].status if ordered else None

    # Recovery window starts when the fault was activated (the application's
    # own failure happens after that), or at the first attempt otherwise.
    window_start = fault_activation_at or (ordered[0].started_at if ordered else None)
    duration_ms: int | None = None
    if window_start is not None and finished_at is not None:
        duration_ms = int(_seconds_between(window_start, finished_at) * 1000)

    observation = {
        "attempt_count": attempt_count,
        "retry_request_count": int(retry_request_count),
        "subsequent_attempt_count": max(0, attempt_count - 1),
        "fault_activated": bool(fault_activated),
        "recovery_duration_ms": duration_ms,
        "final_execution_state": final_state,
        "attempts": [
            {
                "index": attempt.index,
                "started_at": attempt.started_at.isoformat(),
                "finished_at": (
                    attempt.finished_at.isoformat() if attempt.finished_at is not None else None
                ),
                "status": attempt.status,
                "retry_requested": attempt.retry_requested,
            }
            for attempt in ordered
        ],
        "policy": policy.to_dict(),
        "scope": "execution_recovery_only",
        "note": (
            "Execution-level recovery only: no business-effect verification is "
            "performed in this phase."
        ),
    }
    return ObservationResult(
        attempt_count=attempt_count,
        retry_request_count=int(retry_request_count),
        subsequent_attempt_count=max(0, attempt_count - 1),
        fault_activated=bool(fault_activated),
        recovery_duration_ms=duration_ms,
        final_execution_state=final_state,
        evidence_complete=not missing,
        missing_evidence=tuple(dict.fromkeys(missing)),
        observation=observation,
        evidence=tuple(record.to_dict() for record in evidence),
    )


@dataclass(frozen=True)
class VerdictResult:
    verdict: str
    reasons: tuple[dict[str, Any], ...]
    checks: tuple[dict[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict == VERDICT_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": [dict(reason) for reason in self.reasons],
            "checks": [dict(check) for check in self.checks],
            "scope": "execution_recovery_only",
        }


def _reason(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": "verdict", "message": message}


def evaluate(
    *,
    policy: RecoveryPolicy,
    observation: ObservationResult,
    runner_failure: str | None = None,
    scenario_id: str | None = None,
) -> VerdictResult:
    """Decide PASS / FAIL / INCONCLUSIVE / INVALID_RUN / ERROR deterministically."""
    checks: list[dict[str, Any]] = []

    if runner_failure:
        # VeriQ's own infrastructure failed: never blame the application.
        return VerdictResult(
            verdict=VERDICT_ERROR,
            reasons=(
                _reason(
                    "RUNNER_INFRASTRUCTURE_FAILURE",
                    f"VeriQ infrastructure failed and prevented a valid evaluation: {runner_failure}",
                ),
            ),
            checks=(),
        )

    if not observation.fault_activated:
        return VerdictResult(
            verdict=VERDICT_INVALID_RUN,
            reasons=(
                _reason(
                    "FAULT_NOT_ACTIVATED",
                    "The configured fault was never activated, so the intended test did not occur.",
                ),
            ),
            checks=(),
        )

    if not observation.evidence_complete:
        checks.append(
            {
                "check": "evidence_complete",
                "ok": False,
                "detail": ", ".join(observation.missing_evidence) or "incomplete",
            }
        )
        return VerdictResult(
            verdict=VERDICT_INCONCLUSIVE,
            reasons=(
                _reason(
                    "EVIDENCE_INCOMPLETE",
                    "Execution evidence is incomplete ("
                    + ", ".join(observation.missing_evidence)
                    + "), so recovery cannot be judged.",
                ),
            ),
            checks=tuple(checks),
        )
    checks.append({"check": "evidence_complete", "ok": True, "detail": "all required facts observed"})

    violations: list[dict[str, Any]] = []

    attempt_ok = observation.attempt_count <= policy.max_attempts
    checks.append(
        {
            "check": "attempt_limit",
            "ok": attempt_ok,
            "detail": f"{observation.attempt_count} attempt(s), limit {policy.max_attempts}",
        }
    )
    if not attempt_ok:
        violations.append(
            _reason(
                "RETRY_LIMIT_EXCEEDED",
                f"Observed {observation.attempt_count} attempts, above the configured "
                f"maximum of {policy.max_attempts}.",
            )
        )

    if policy.expect_retry is True:
        retried = observation.retry_request_count > 0
        checks.append(
            {
                "check": "retry_requested",
                "ok": retried,
                "detail": f"{observation.retry_request_count} retry request(s)",
            }
        )
        if not retried:
            violations.append(
                _reason(
                    "EXPECTED_RETRY_NOT_REQUESTED",
                    "The recovery policy expects a retry request, but none was observed.",
                )
            )
    elif policy.expect_retry is False:
        unexpected = observation.retry_request_count > 0
        checks.append(
            {
                "check": "retry_requested",
                "ok": not unexpected,
                "detail": f"{observation.retry_request_count} retry request(s)",
            }
        )
        if unexpected:
            violations.append(
                _reason(
                    "UNEXPECTED_RETRY",
                    "The recovery policy expects a terminal failure without retry, but a "
                    "retry was requested.",
                )
            )

    if observation.retry_request_count > 0 and observation.attempt_count < 2:
        violations.append(
            _reason(
                "RETRY_WITHOUT_SUBSEQUENT_ATTEMPT",
                "A retry was requested but no subsequent execution attempt was observed; "
                "a retry request is not proof that the retry happened.",
            )
        )

    if policy.expected_terminal_state != TERMINAL_ANY:
        state_ok = observation.final_execution_state == policy.expected_terminal_state
        checks.append(
            {
                "check": "terminal_state",
                "ok": state_ok,
                "detail": (
                    f"observed {observation.final_execution_state or 'none'}, "
                    f"expected {policy.expected_terminal_state}"
                ),
            }
        )
        if not state_ok:
            violations.append(
                _reason(
                    "TERMINAL_STATE_MISMATCH",
                    f"Final execution state was "
                    f"{observation.final_execution_state or 'unobserved'}, expected "
                    f"{policy.expected_terminal_state}.",
                )
            )

    deadline_ms = policy.recovery_deadline_seconds * 1000
    deadline_ok = observation.recovery_duration_ms is None or (
        observation.recovery_duration_ms <= deadline_ms
    )
    checks.append(
        {
            "check": "recovery_deadline",
            "ok": deadline_ok,
            "detail": (
                f"{observation.recovery_duration_ms} ms observed, "
                f"deadline {deadline_ms} ms"
            ),
        }
    )
    if not deadline_ok:
        violations.append(
            _reason(
                "RECOVERY_DEADLINE_EXCEEDED",
                "Recovery took longer than the configured recovery deadline.",
            )
        )

    if policy.expect_redelivery is not None:
        redelivered = observation.attempt_count >= 2
        redelivery_ok = redelivered == policy.expect_redelivery
        checks.append(
            {
                "check": "redelivery",
                "ok": redelivery_ok,
                "detail": f"{observation.attempt_count} attempt(s)",
            }
        )
        if not redelivery_ok:
            violations.append(
                _reason(
                    "REDELIVERY_EXPECTATION_MISMATCH",
                    "Observed delivery/execution count does not match the configured "
                    "redelivery expectation; Celery redelivery depends on acknowledgement "
                    "settings and broker behaviour.",
                )
            )

    if violations:
        return VerdictResult(
            verdict=VERDICT_FAIL, reasons=tuple(violations), checks=tuple(checks)
        )
    return VerdictResult(
        verdict=VERDICT_PASS,
        reasons=(
            _reason(
                "RECOVERY_POLICY_SATISFIED",
                "The fault was activated and observed recovery met the configured policy.",
            ),
        ),
        checks=tuple(checks),
    )


__all__ = [
    "AttemptView",
    "EvidenceRecord",
    "ObservationResult",
    "RecoveryPolicy",
    "SOURCE_BROKER",
    "SOURCE_INJECTOR",
    "SOURCE_RUNNER",
    "SOURCE_SDK",
    "VerdictResult",
    "VERDICT_ERROR",
    "VERDICT_FAIL",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_INVALID_RUN",
    "VERDICT_PASS",
    "derive_observation",
    "evaluate",
]
