import uuid
from datetime import datetime, timedelta, timezone

import pytest

from veriq import VeriQEvent
from veriq.exceptions import VeriQValidationError


def test_event_ids_are_unique_and_valid_uuids():
    run_id = uuid.uuid4()
    first = VeriQEvent.create(run_id, "sdk.test_event")
    second = VeriQEvent.create(run_id, "sdk.test_event")
    assert isinstance(first.event_id, uuid.UUID)
    assert first.event_id != second.event_id


def test_occurred_at_defaults_to_timezone_aware_utc():
    event = VeriQEvent.create(uuid.uuid4(), "sdk.test_event")
    assert event.occurred_at.tzinfo is not None
    assert event.occurred_at.utcoffset() == timedelta(0)


def test_supplied_occurred_at_is_normalized_to_utc():
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 11, 11, 12, 0, tzinfo=plus_two)
    event = VeriQEvent.create(uuid.uuid4(), "sdk.test_event", occurred_at=local)
    assert event.occurred_at == datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
    assert event.occurred_at.utcoffset() == timedelta(0)


def test_serialization_matches_backend_contract():
    run_id = uuid.uuid4()
    event_id = uuid.uuid4()
    occurred_at = datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc)
    event = VeriQEvent.create(
        str(run_id),
        "  sdk.test_event  ",
        {"message": "SDK communication successful"},
        occurred_at=occurred_at,
        event_id=str(event_id),
    )
    assert event.to_request_body() == {
        "event_id": str(event_id),
        "event_type": "sdk.test_event",
        "occurred_at": "2026-11-11T10:30:00+00:00",
        "payload": {"message": "SDK communication successful"},
    }
    assert event.experiment_run_id == run_id


def test_payload_is_optional_and_omitted_when_absent():
    body = VeriQEvent.create(uuid.uuid4(), "sdk.test_event").to_request_body()
    assert "payload" not in body


def test_naive_timestamp_is_rejected():
    with pytest.raises(VeriQValidationError, match="timezone-aware"):
        VeriQEvent.create(uuid.uuid4(), "sdk.test_event", occurred_at=datetime(2026, 11, 11))


@pytest.mark.parametrize("bad_run_id", ["not-a-uuid", "", None])
def test_invalid_run_id_is_rejected(bad_run_id):
    with pytest.raises(VeriQValidationError, match="experiment_run_id"):
        VeriQEvent.create(bad_run_id, "sdk.test_event")


@pytest.mark.parametrize("bad_type", ["", "   ", "x" * 101, 42])
def test_invalid_event_type_is_rejected(bad_type):
    with pytest.raises(VeriQValidationError, match="event_type"):
        VeriQEvent.create(uuid.uuid4(), bad_type)


def test_non_dict_payload_is_rejected():
    with pytest.raises(VeriQValidationError, match="payload"):
        VeriQEvent.create(uuid.uuid4(), "sdk.test_event", payload=["not", "a", "dict"])
