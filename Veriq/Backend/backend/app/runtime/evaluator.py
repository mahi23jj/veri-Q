"""Reliability Evaluator.

A thin, deterministic wrapper around :mod:`app.domain.runtime.recovery`: no LLM,
no heuristics, no clock. Given the same persisted evidence it returns the same
verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.runtime.recovery import (
    ObservationResult,
    RecoveryPolicy,
    VerdictResult,
    evaluate,
)


@dataclass
class ReliabilityEvaluator:
    def evaluate(
        self,
        *,
        policy: RecoveryPolicy,
        observation: ObservationResult,
        scenario_id: str | None = None,
        runner_failure: str | None = None,
    ) -> VerdictResult:
        return evaluate(
            policy=policy,
            observation=observation,
            runner_failure=runner_failure,
            scenario_id=scenario_id,
        )


__all__ = ["ReliabilityEvaluator"]
