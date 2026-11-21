"""Test case run lifecycle state machine (pure).

The lifecycle answers "where is VeriQ in the test?"; the verdict answers "did
the application recover?". They are never collapsed into one field.
"""

from __future__ import annotations

LIFECYCLE_STATES = (
    "PENDING",
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
    "FAILED",
    "CANCELLED",
)

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})

# Forward edges only. ``FINALIZING`` is reachable from every non-terminal state
# so cancellation and error paths always run the same cleanup sequence.
_ALLOWED: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"VALIDATING", "FINALIZING", "FAILED", "CANCELLED"}),
    "VALIDATING": frozenset({"PROVISIONING", "FINALIZING", "FAILED", "CANCELLED"}),
    "PROVISIONING": frozenset({"PREPARING_FAULT", "FINALIZING", "FAILED", "CANCELLED"}),
    "PREPARING_FAULT": frozenset({"STARTING", "FINALIZING", "FAILED", "CANCELLED"}),
    "STARTING": frozenset({"RUNNING", "FINALIZING", "FAILED", "CANCELLED"}),
    "RUNNING": frozenset(
        {"INJECTING", "OBSERVING_RECOVERY", "FINALIZING", "FAILED", "CANCELLED"}
    ),
    "INJECTING": frozenset(
        {"OBSERVING_RECOVERY", "FINALIZING", "FAILED", "CANCELLED"}
    ),
    "OBSERVING_RECOVERY": frozenset(
        {"EVALUATING", "FINALIZING", "FAILED", "CANCELLED"}
    ),
    "EVALUATING": frozenset({"FINALIZING", "FAILED", "CANCELLED"}),
    "FINALIZING": frozenset({"COMPLETED", "FAILED", "CANCELLED"}),
    "COMPLETED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}


class InvalidTransitionError(Exception):
    """The requested lifecycle transition is not allowed."""


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: str, target: str) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(f"{current} -> {target} is not allowed")


def next_states(state: str) -> tuple[str, ...]:
    return tuple(sorted(_ALLOWED.get(state, frozenset())))


__all__ = [
    "InvalidTransitionError",
    "LIFECYCLE_STATES",
    "TERMINAL_STATES",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "next_states",
]
