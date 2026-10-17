from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from swe.domain.job import JobStateName
from swe.domain.request import (
    DeliveryRequest,
    QuoteAccepted,
    QuoteIssued,
    QuoteStatus,
    RequestLogged,
    RequestStatus,
)
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now

T = now()


def window(start_hours: int) -> tuple:
    return (T + timedelta(hours = start_hours), T + timedelta(hours = start_hours + 2))


DETAILS = dict(
    customer_id = "cust-1", contact_name = "Sam", contact_phone = "0400000000",
    parcels = [{"size": "small", "weight_kg": "2.5"}],
    pickup_address = {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
    dropoff_address = {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
)


def quote_args(**overrides) -> dict:
    return dict(
        price = Decimal("50"), eta_pickup = window(1), eta_dropoff = window(4),
        valid_for = timedelta(hours = 24), issued_by = "staff-1", at = T,
    ) | overrides


@pytest.fixture
def request_():
    request, _ = DeliveryRequest.log(**DETAILS)
    return request


def test_log_produces_event():
    request, event = DeliveryRequest.log(**DETAILS)
    assert isinstance(event, RequestLogged)
    assert event.request_id == request.request_id


@pytest.mark.parametrize("override", [
    {"parcels": []},
    {"pickup_address": {**DETAILS["pickup_address"], "postcode": "x"}},
    {"dropoff_address": DETAILS["pickup_address"]},
])
def test_invalid_request_refused(override):
    with pytest.raises(ValidationError):
        DeliveryRequest.log(**DETAILS | override)


def test_invalid_quote_leaves_request_unchanged(request_):
    with pytest.raises(ValidationError):
        request_.issue_quote(**quote_args(eta_pickup = window(1)[::-1]), previous = None)
    assert request_.current_quote_id is None


def test_revision_supersedes_previous(request_):
    q1, first = request_.issue_quote(**quote_args(), previous = None)
    assert first.supersedes is None
    q2, issued = request_.issue_quote(**quote_args(price = Decimal("45")), previous = q1)
    assert isinstance(issued, QuoteIssued) and issued.supersedes == q1.quote_id
    assert q1.status is QuoteStatus.SUPERSEDED
    assert request_.current_quote_id == q2.quote_id


def test_issue_requires_current_quote(request_):
    request_.issue_quote(**quote_args(), previous = None)
    with pytest.raises(DomainError):
        request_.issue_quote(**quote_args(), previous = None)


def test_accept_creates_unallocated_job(request_):
    quote, _ = request_.issue_quote(**quote_args(), previous = None)
    job, event = request_.accept_quote(quote, by = "cust-1", at = T)
    assert quote.status is QuoteStatus.ACCEPTED
    assert request_.status is RequestStatus.ACCEPTED
    assert job.state is JobStateName.UNALLOCATED
    assert (job.request_id, job.quote_id) == (request_.request_id, quote.quote_id)
    assert isinstance(event, QuoteAccepted)


def test_cannot_accept_superseded_quote(request_):
    q1, _ = request_.issue_quote(**quote_args(), previous = None)
    request_.issue_quote(**quote_args(), previous = q1)
    with pytest.raises(DomainError):
        request_.accept_quote(q1, by = "cust-1", at = T)


def test_cannot_accept_expired_quote(request_):
    quote, _ = request_.issue_quote(**quote_args(), previous = None)
    with pytest.raises(DomainError, match = "expired"):
        request_.accept_quote(quote, by = "cust-1", at = T + timedelta(days = 2))
    assert quote.status is QuoteStatus.PENDING


def test_accepted_request_is_closed_to_changes(request_):
    quote, _ = request_.issue_quote(**quote_args(), previous = None)
    request_.accept_quote(quote, by = "cust-1", at = T)
    with pytest.raises(DomainError):
        request_.accept_quote(quote, by = "cust-1", at = T)
    with pytest.raises(DomainError):
        request_.cancel(by = "cust-1")


def test_issued_terms_are_frozen(request_):
    quote, _ = request_.issue_quote(**quote_args(), previous = None)
    with pytest.raises(ValidationError):
        quote.price = Decimal("1")

