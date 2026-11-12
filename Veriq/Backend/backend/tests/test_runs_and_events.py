"""Model-level tests for runs/events (no execution engine exists yet)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Experiment, ExperimentEvent, ExperimentRun, TargetApp


def _experiment(db: Session) -> Experiment:
    app = TargetApp(name="model-app")
    db.add(app)
    db.flush()
    exp = Experiment(
        target_app_id=app.id,
        name="exp",
        task_name="tasks.charge",
        scenario="crash_after_commit",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def _run(exp: Experiment, run_number: int = 1) -> ExperimentRun:
    return ExperimentRun(
        experiment_id=exp.id,
        run_number=run_number,
        status="PENDING",
        config_snapshot={"scenario": exp.scenario, "timeout_seconds": exp.timeout_seconds},
        created_at=datetime.now(timezone.utc),
    )


def test_run_number_unique_within_experiment(db_session: Session):
    exp = _experiment(db_session)
    db_session.add(_run(exp, 1))
    db_session.commit()
    db_session.add(_run(exp, 1))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_same_run_number_allowed_for_different_experiments(db_session: Session):
    exp1 = _experiment(db_session)
    app2 = TargetApp(name="model-app-2")
    db_session.add(app2)
    db_session.flush()
    exp2 = Experiment(target_app_id=app2.id, name="exp2", task_name="t", scenario="crash_after_commit")
    db_session.add(exp2)
    db_session.flush()
    db_session.add(_run(exp1, 1))
    db_session.add(_run(exp2, 1))
    db_session.commit()  # must not raise


def test_event_associated_with_valid_run(db_session: Session):
    exp = _experiment(db_session)
    run = _run(exp, 1)
    db_session.add(run)
    db_session.commit()
    event = ExperimentEvent(
        experiment_run_id=run.id,
        event_type="run_created",
        source="API",
        payload={"run_number": 1},
        occurred_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()
    assert event.experiment_run_id == run.id
    assert run.events[0].event_type == "run_created"


def test_events_preserve_occurrence_order_not_arrival_order(db_session: Session):
    exp = _experiment(db_session)
    run = _run(exp, 1)
    db_session.add(run)
    db_session.commit()
    now = datetime.now(timezone.utc)
    # Insert the later event first.
    db_session.add(ExperimentEvent(experiment_run_id=run.id, event_type="second", source="RUNNER", occurred_at=now))
    db_session.add(ExperimentEvent(experiment_run_id=run.id, event_type="first", source="RUNNER", occurred_at=now - timedelta(seconds=5)))
    db_session.commit()
    ordered = (
        db_session.query(ExperimentEvent)
        .filter_by(experiment_run_id=run.id)
        .order_by(ExperimentEvent.occurred_at)
        .all()
    )
    assert [e.event_type for e in ordered] == ["first", "second"]
