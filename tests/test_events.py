import json
from datetime import timedelta
from decimal import Decimal

import pytest

from swe.app import DeliveryManagementSystem
from swe.domain.job import DeliveryJob, JobCreated, JobStateName
from swe.domain.request import DeliveryRequest, QuoteAccepted, QuoteIssued, RequestLogged
from swe.domain.shared import HistoryEvent, parse_history_event
from swe.domain.shared.ids import now
from swe.events import handlers
from swe.events.handling import handles
from swe.events.routes import ROUTES
from swe.events.stream_publisher import to_event
from swe.repo.schemas import schema_for

DETAILS = dict(
    customer_id="cust-1",
    contact_name="Sam",
    contact_phone="0400000000",
    parcels=[{"size": "small", "weight_kg": "2.5"}],
    pickup_address={"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
    dropoff_address={"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
)


def accepted_flow():
    t = now()
    request, logged = DeliveryRequest.log(**DETAILS)
    quote, issued = request.issue_quote(
        price=Decimal("50"),
        valid_for=timedelta(hours=24),
        issued_by="staff-1",
        previous=None,
        eta_pickup=(t + timedelta(hours=1), t + timedelta(hours=3)),
        eta_dropoff=(t + timedelta(hours=4), t + timedelta(hours=6)),
    )
    accepted = request.accept_quote(quote, by="cust-1")
    _, created = DeliveryJob.create(
        job_id=accepted.job_id, request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"
    )
    return logged, issued, accepted, created


# what DynamoDB stores, then hands back on the stream
def stream_record(event) -> dict:
    return {"eventName": "INSERT", "dynamodb": {"NewImage": schema_for(event).to_item(event)}}


# what EventBridge invokes a handler Lambda with
def eventbridge_event(entry: dict) -> dict:
    return {
        "id": "evt-1",
        "source": entry["Source"],
        "detail-type": entry["DetailType"],
        "time": now().isoformat(),
        "detail": json.loads(entry["Detail"]),
    }


def test_domain_methods_return_specific_event_types():
    logged, issued, accepted, created = accepted_flow()
    assert isinstance(logged, RequestLogged) and logged.customer_id == "cust-1"
    assert isinstance(issued, QuoteIssued) and issued.price == Decimal("50")
    assert isinstance(accepted, QuoteAccepted) and accepted.customer_id == "cust-1"
    assert isinstance(created, JobCreated) and created.job_id == accepted.job_id


def test_parse_picks_subclass_from_discriminator():
    _, issued, accepted, created = accepted_flow()
    for event in (issued, accepted, created):
        parsed = parse_history_event(event.model_dump())
        assert type(parsed) is type(event) and parsed == event


def test_parse_rejects_missing_fields():
    with pytest.raises(ValueError):
        parse_history_event({"event_type": "quote_accepted", "request_id": "r1", "quote_id": "q1"})  # no job_id


# DynamoDB writers drop None attributes, so optional fields must parse when absent
def test_stream_to_handler_round_trip():
    logged, issued, accepted, created = accepted_flow()
    for event in (logged, issued, accepted, created):
        entry = to_event(stream_record(event))
        assert entry["DetailType"] == event.event_type
        assert "pk" not in entry["Detail"]
        assert parse_history_event(json.loads(entry["Detail"])) == event


def test_stream_skips_non_event_items():
    record = {"eventName": "INSERT", "dynamodb": {"NewImage": {"pk": {"S": "REQUEST#1"}, "sk": {"S": "METADATA"}}}}
    assert to_event(record) is None


def test_handler_receives_typed_event_and_refuses_others():
    _, issued, accepted, _ = accepted_flow()
    received = []

    @handles(QuoteAccepted)
    def handler(event: QuoteAccepted) -> None:
        received.append(event)

    handler(eventbridge_event(to_event(stream_record(accepted))))
    assert received == [accepted]
    with pytest.raises(TypeError):
        handler(eventbridge_event(to_event(stream_record(issued))))


# the event as it reaches the Lambda, through to the saved job; redelivery does nothing
def test_create_delivery_job_handler(repo, monkeypatch):
    request, _ = DeliveryRequest.log(**DETAILS)
    t = now()
    quote, _ = request.issue_quote(
        price=Decimal("50"),
        valid_for=timedelta(hours=24),
        issued_by="staff-1",
        previous=None,
        eta_pickup=(t + timedelta(hours=1), t + timedelta(hours=3)),
        eta_dropoff=(t + timedelta(hours=4), t + timedelta(hours=6)),
    )
    accepted = request.accept_quote(quote, by="cust-1")
    monkeypatch.setattr(handlers, "system", lambda: DeliveryManagementSystem(repo))

    invocation = eventbridge_event(to_event(stream_record(accepted)))
    handlers.create_delivery_job(invocation)
    handlers.create_delivery_job(invocation)

    job = repo.get_job(accepted.job_id)
    assert (job.request_id, job.quote_id, job.customer_id) == (request.request_id, quote.quote_id, "cust-1")
    assert job.state is JobStateName.UNALLOCATED
    assert [e.event_type for e in repo.get_history(request.request_id)] == ["job_created"]


def test_routes_declare_event_types():
    assert ROUTES["create-delivery-job"].event_types == ["quote_accepted"]
    assert ROUTES["notify-office-staff"].event_types == [
        "request_logged",
        "job_created",
        "quote_rejected",
        "payment_recorded",
        "payment_adjusted",
    ]
    assert ROUTES["notify-customer"].event_types == ["quote_issued", "request_cancelled", "job_closed"]
    assert ROUTES["audit"].event_types is None


def test_parse_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="unknown event_type"):
        parse_history_event({"event_type": "nope", "request_id": "r1"})


def test_events_register_themselves():
    assert HistoryEvent.registry["quote_accepted"] is QuoteAccepted
    assert QuoteAccepted.TYPE == "quote_accepted"


def test_duplicate_event_type_is_refused():
    from typing import Literal

    with pytest.raises(TypeError, match="already used by QuoteAccepted"):

        class Clash(HistoryEvent):
            event_type: Literal["quote_accepted"] = "quote_accepted"
