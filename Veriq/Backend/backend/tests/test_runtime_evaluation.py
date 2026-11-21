"""Pure runtime domain: recovery policy, observations, verdicts, lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.runtime.lifecycle import (
    InvalidTransitionError,
    assert_transition,
    can_transition,
    is_terminal,
    next_states,
)
from app.domain.runtime.recovery import (
    AttemptView,
    EvidenceRecord,
    RecoveryPolicy,
    SOURCE_SDK,
    derive_observation,
    evaluate,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _attempts(*statuses: str, retry_first: bool = False) -> list[AttemptView]:
    attempts = []
    for index, status in enumerate(statuses, start=1):
        attempts.append(
            AttemptView(
                index=index,
                started_at=NOW + timedelta(seconds=index * 2),
                finished_at=NOW + timedelta(seconds=index * 2 + 1),
                status=status,
                retry_requested=retry_first and index == 1,
            )
        )
    return attempts


def _observation(*, attempts=(), retries=0, activated=True, submitted=True):
    return derive_observation(
        policy=RecoveryPolicy(settle_seconds=1),
        attempts=list(attempts),
        retry_request_count=retries,
        fault_activated=activated,
        task_submitted=submitted,
        evidence=[
            EvidenceRecord(
                source=SOURCE_SDK,
                event_type="TASK_STARTED",
                occurred_at=NOW,
                detail={"attempt": 1},
            )
        ],
        fault_activation_at=NOW,
    )


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_policy_defaults_and_validation():
    default = RecoveryPolicy.from_contract({})
    assert default.max_attempts == 3
    assert default.expected_terminal_state == "SUCCEEDED"
    assert default.expect_retry is None

    invalid = RecoveryPolicy.from_contract(
        {
            "recovery": {
                "max_attempts": 0,
                "recovery_deadline_seconds": 999999,
                "expected_terminal_state": "MAYBE",
                "expect_retry": "yes",
            }
        }
    )
    assert invalid.max_attempts == 3
    assert invalid.recovery_deadline_seconds == 120
    assert invalid.expected_terminal_state == "SUCCEEDED"
    assert invalid.expect_retry is None


def test_policy_reads_contract_values():
    policy = RecoveryPolicy.from_contract(
        {
            "recovery": {
                "max_attempts": 5,
                "expected_terminal_state": "FAILED",
                "expect_retry": False,
                "expect_redelivery": True,
                "settle_seconds": 4,
            }
        }
    )
    assert policy.max_attempts == 5
    assert policy.expected_terminal_state == "FAILED"
    assert policy.expect_retry is False
    assert policy.expect_redelivery is True
    assert policy.settle_seconds == 4


def test_policy_round_trips_through_dict():
    policy = RecoveryPolicy(max_attempts=2, expect_retry=True)
    assert RecoveryPolicy.from_contract({"recovery": policy.to_dict()}) == policy


# ---------------------------------------------------------------------------
# Observation derivation
# ---------------------------------------------------------------------------


def test_observation_measures_attempts_and_recovery_window():
    observation = _observation(
        attempts=_attempts("FAILED", "SUCCEEDED"), retries=1
    )
    assert observation.attempt_count == 2
    assert observation.subsequent_attempt_count == 1
    assert observation.retry_request_count == 1
    assert observation.final_execution_state == "SUCCEEDED"
    assert observation.evidence_complete is True
    # fault activated at NOW, last attempt finished at +5s
    assert observation.recovery_duration_ms == 5000
    assert observation.evidence[0]["source"] == "SDK"


def test_observation_records_missing_terminal_event_instead_of_assuming():
    attempts = [
        AttemptView(
            index=1,
            started_at=NOW,
            finished_at=None,
            status="RUNNING",
        )
    ]
    observation = _observation(attempts=attempts)
    assert observation.evidence_complete is False
    assert "TERMINAL_EXECUTION_EVENT_MISSING" in observation.missing_evidence
    assert observation.final_execution_state == "RUNNING"


def test_observation_flags_unobserved_execution():
    observation = _observation(attempts=(), submitted=True)
    assert observation.evidence_complete is False
    assert "TASK_ATTEMPT_NOT_OBSERVED" in observation.missing_evidence


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_pass_when_recovery_matches_policy():
    policy = RecoveryPolicy(expect_retry=True)
    observation = _observation(attempts=_attempts("FAILED", "SUCCEEDED"), retries=1)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "PASS"
    assert result.ok


def test_fail_when_retry_requested_but_no_subsequent_attempt():
    policy = RecoveryPolicy(expect_retry=True)
    observation = _observation(attempts=_attempts("RETRYING"), retries=1)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "FAIL"
    codes = {reason["code"] for reason in result.reasons}
    assert "RETRY_WITHOUT_SUBSEQUENT_ATTEMPT" in codes


def test_fail_when_terminal_state_does_not_match():
    policy = RecoveryPolicy(expected_terminal_state="FAILED", expect_retry=False)
    observation = _observation(attempts=_attempts("SUCCEEDED"))
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "FAIL"
    assert "TERMINAL_STATE_MISMATCH" in {reason["code"] for reason in result.reasons}


def test_fail_when_retry_limit_exceeded():
    policy = RecoveryPolicy(max_attempts=2)
    observation = _observation(attempts=_attempts("FAILED", "FAILED", "SUCCEEDED"), retries=2)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "FAIL"
    assert "RETRY_LIMIT_EXCEEDED" in {reason["code"] for reason in result.reasons}


def test_fail_when_recovery_deadline_exceeded():
    policy = RecoveryPolicy(recovery_deadline_seconds=1)
    observation = _observation(attempts=_attempts("FAILED", "SUCCEEDED"), retries=1)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "FAIL"
    assert "RECOVERY_DEADLINE_EXCEEDED" in {reason["code"] for reason in result.reasons}


def test_fail_when_unexpected_retry_happens():
    policy = RecoveryPolicy(expect_retry=False, expected_terminal_state="ANY")
    observation = _observation(attempts=_attempts("FAILED", "FAILED"), retries=1)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "FAIL"
    assert "UNEXPECTED_RETRY" in {reason["code"] for reason in result.reasons}


def test_redelivery_expectation_is_judged_on_observed_attempts():
    policy = RecoveryPolicy(expect_redelivery=True, expect_retry=None)
    single = evaluate(
        policy=policy, observation=_observation(attempts=_attempts("FAILED"))
    )
    assert single.verdict == "FAIL"
    assert "REDELIVERY_EXPECTATION_MISMATCH" in {
        reason["code"] for reason in single.reasons
    }

    redelivered = evaluate(
        policy=policy, observation=_observation(attempts=_attempts("FAILED", "SUCCEEDED"))
    )
    assert redelivered.verdict == "PASS"


def test_inconclusive_when_evidence_is_incomplete():
    policy = RecoveryPolicy()
    attempts = [AttemptView(index=1, started_at=NOW, finished_at=None, status="RUNNING")]
    result = evaluate(policy=policy, observation=_observation(attempts=attempts))
    assert result.verdict == "INCONCLUSIVE"
    assert "EVIDENCE_INCOMPLETE" in {reason["code"] for reason in result.reasons}


def test_invalid_run_when_fault_never_activated():
    policy = RecoveryPolicy()
    observation = _observation(attempts=_attempts("SUCCEEDED"), activated=False)
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "INVALID_RUN"
    assert result.reasons[0]["code"] == "FAULT_NOT_ACTIVATED"


def test_error_when_runner_failed_even_if_app_succeeded():
    policy = RecoveryPolicy()
    observation = _observation(attempts=_attempts("SUCCEEDED"))
    result = evaluate(
        policy=policy,
        observation=observation,
        runner_failure="RuntimeBackendError: docker unavailable",
    )
    assert result.verdict == "ERROR"
    assert result.reasons[0]["code"] == "RUNNER_INFRASTRUCTURE_FAILURE"


def test_conflicting_evidence_is_inconclusive_not_pass():
    policy = RecoveryPolicy()
    observation = derive_observation(
        policy=policy,
        attempts=_attempts("SUCCEEDED"),
        retry_request_count=0,
        fault_activated=True,
        task_submitted=True,
        extra_missing=["CONFLICTING_EXECUTION_EVIDENCE"],
    )
    result = evaluate(policy=policy, observation=observation)
    assert result.verdict == "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_happy_path_transitions_are_allowed():
    state = "PENDING"
    for target in (
        "VALIDATING",
        "PROVISIONING",
        "PREPARING_FAULT",
        "STARTING",
        "RUNNING",
        "INJECTING",
        "OBSERVING_RECOVERY",
        "EVALUATING",
        "FINALIZING",
        "COMPLETED",
    ):
        assert can_transition(state, target), (state, target)
        state = target
    assert is_terminal(state)
    assert next_states(state) == ()


def test_lifecycle_cannot_skip_forward_or_leave_terminal():
    assert not can_transition("PENDING", "RUNNING")
    assert not can_transition("COMPLETED", "VALIDATING")
    with pytest.raises(InvalidTransitionError):
        assert_transition("COMPLETED", "RUNNING")


def test_every_non_terminal_state_can_finalize():
    for state in ("PENDING", "VALIDATING", "PROVISIONING", "STARTING", "RUNNING"):
        assert can_transition(state, "FINALIZING"), state
