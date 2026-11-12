import logging
import uuid

import pytest

from veriq import EventReceipt, VeriQ, VeriQConfig
from veriq.exceptions import (
    VeriQAuthenticationError,
    VeriQClientClosedError,
    VeriQConfigError,
)
from veriq.transport.http import HTTPTransport

from .conftest import API_KEY, API_URL, MockBackend, event_response, make_config, make_transport


def test_construction_requires_url_and_key():
    with pytest.raises(VeriQConfigError):
        VeriQ()
    with pytest.raises(VeriQConfigError):
        VeriQ(api_url=API_URL)
    with pytest.raises(VeriQConfigError):
        VeriQ(api_key=API_KEY)
    with pytest.raises(VeriQConfigError):
        VeriQ(api_url=API_URL, api_key=API_KEY, config=make_config())


def test_send_event_returns_receipt(veriq: VeriQ, backend: MockBackend):
    run_id = uuid.uuid4()
    server_id = uuid.uuid4()
    backend.reply(201, event_response(server_id))

    receipt = veriq.send_event(
        experiment_run_id=run_id,
        event_type="sdk.test_event",
        payload={"message": "SDK communication successful"},
    )

    assert isinstance(receipt, EventReceipt)
    assert receipt.server_event_id == server_id
    assert receipt.event_id != server_id
    assert receipt.experiment_run_id == run_id
    assert receipt.duplicate is False
    assert receipt.status_code == 201


def test_duplicate_submission_is_flagged(veriq: VeriQ, backend: MockBackend):
    server_id = uuid.uuid4()
    event_id = uuid.uuid4()
    payload = {"message": "retry"}
    backend.reply(201, event_response(server_id)).reply(200, event_response(server_id))

    run_id = uuid.uuid4()
    first = veriq.send_event(run_id, "sdk.test_event", payload, event_id=event_id)
    second = veriq.send_event(run_id, "sdk.test_event", payload, event_id=event_id)

    assert first.duplicate is False and second.duplicate is True
    assert first.server_event_id == second.server_event_id
    # The same idempotency key travels on both requests.
    assert backend.json_bodies[0]["event_id"] == backend.json_bodies[1]["event_id"] == str(event_id)


def test_context_manager_closes_the_client(backend: MockBackend):
    transport = make_transport(backend)
    with VeriQ(transport=transport) as veriq_client:
        assert not veriq_client.closed
    assert veriq_client.closed
    with pytest.raises(VeriQClientClosedError):
        veriq_client.send_event(uuid.uuid4(), "sdk.test_event")


def test_send_after_close_raises(veriq: VeriQ):
    veriq.close()
    veriq.close()  # idempotent
    with pytest.raises(VeriQClientClosedError):
        veriq.send_event(uuid.uuid4(), "sdk.test_event")


def test_repr_hides_the_api_key(veriq: VeriQ):
    assert API_KEY not in repr(veriq)
    assert API_URL in repr(veriq)


def test_credentials_are_never_logged(backend: MockBackend, caplog: pytest.LogCaptureFixture):
    backend.reply(401, {"detail": "invalid or missing API key"})
    caplog.set_level(logging.DEBUG)
    transport: HTTPTransport = make_transport(backend)
    veriq_client = VeriQ(transport=transport)

    with pytest.raises(VeriQAuthenticationError) as excinfo:
        veriq_client.send_event(uuid.uuid4(), "sdk.test_event", {"message": "x"})

    veriq_client.close()
    assert API_KEY not in str(excinfo.value)
    assert API_KEY not in caplog.text
    assert API_KEY not in repr(transport)
    assert API_KEY not in repr(veriq_client)
