"""Importing this package registers every model on Base.metadata (for Alembic)."""

from app.models.base import Base
from app.models.experiment import Experiment
from app.models.experiment_event import ExperimentEvent
from app.models.experiment_run import ExperimentRun
from app.models.observation import (
    ExecutionEvent,
    RegisteredTask,
    TaskExecution,
    Worker,
    WorkerQueue,
)
from app.models.planning import (
    AdapterDefinition,
    ApplicationAdapter,
    CheckpointScenarioSelection,
    TaskCheckpoint,
    TaskScenarioSelection,
    TaskTestContract,
    TaskTestContractVersion,
    TestPlan,
    TestPlanRevision,
    TestPlanTestCase,
)
from app.models.target_app import TargetApp

__all__ = [
    "Base",
    "TargetApp",
    "Experiment",
    "ExperimentRun",
    "ExperimentEvent",
    "RegisteredTask",
    "Worker",
    "WorkerQueue",
    "TaskExecution",
    "ExecutionEvent",
    "TaskCheckpoint",
    "TaskScenarioSelection",
    "CheckpointScenarioSelection",
    "TaskTestContract",
    "TaskTestContractVersion",
    "AdapterDefinition",
    "ApplicationAdapter",
    "TestPlan",
    "TestPlanRevision",
    "TestPlanTestCase",
]
