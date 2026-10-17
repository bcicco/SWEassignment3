from datetime import timedelta
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from swe.app import (
    AcceptQuote,
    CancelRequest,
    DeliveryManagementSystem,
    ForbiddenError,
    IssueQuote,
    LogRequest,
    RejectQuote,
    RequestQuoteRevision,
)
from swe.domain.job import JobStateName
from swe.domain.request import QuoteStatus, RequestStatus
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.infra.bootstrap import create_table
from swe.infra.config import TABLE_NAME
from swe.repo import ConflictError, NotFoundError, Repository
from swe.repo.schemas.request import QUOTE

T = now()


@pytest.fixture
def dynamodb(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        create_table(client)
        yield client


@pytest.fixture
def repo(dynamodb):
    return Repository(dynamodb)


# ticks a second per call, like real commands arriving one after another
@pytest.fixture
def dms(repo):
    ticks = iter(range(1000))
    return DeliveryManagementSystem(repo, clock=lambda: T + timedelta(seconds=next(ticks)))


def log(dms, customer_id="cust-1"):
    return dms.log_request(
        LogRequest(
            customer_id=customer_id,
            contact_name="Sam",
            contact_phone="0400000000",
            parcels=[{"size": "small", "weight_kg": "2.5"}],
            pickup_address={"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
            dropoff_address={"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
        )
    )


def issue(dms, request_id, price="50"):
    return dms.issue_quote(
        IssueQuote(
            request_id=request_id,
            staff_id="staff-1",
            price=Decimal(price),
            eta_pickup=(T + timedelta(hours=1), T + timedelta(hours=3)),
            eta_dropoff=(T + timedelta(hours=4), T + timedelta(hours=6)),
        )
    )


def history(dynamodb, request_id) -> list[str]:
    items = dynamodb.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :event)",
        ExpressionAttributeValues={":pk": {"S": f"REQUEST#{request_id}"}, ":event": {"S": "EVENT#"}},
    )["Items"]
    return [i["event_type"]["S"] for i in items]


def test_full_flow_is_saved_with_history(dms, repo, dynamodb):
    request = log(dms)
    q1 = issue(dms, request.request_id)
    q2 = issue(dms, request.request_id, price="45")
    job = dms.accept_quote(AcceptQuote(request_id=request.request_id, quote_id=q2.quote_id, customer_id="cust-1"))

    assert repo.get_request(request.request_id).status is RequestStatus.ACCEPTED
    assert repo.get_quote(request.request_id, q1.quote_id).status is QuoteStatus.SUPERSEDED
    assert repo.get_quote(request.request_id, q2.quote_id).status is QuoteStatus.ACCEPTED
    saved_job = repo.get_job(job.job_id)
    assert (saved_job.state, saved_job.quote_id) == (JobStateName.UNALLOCATED, q2.quote_id)
    assert history(dynamodb, request.request_id) == [
        "request_logged",
        "quote_issued",
        "quote_issued",
        "quote_accepted",
    ]


def test_saved_models_load_back_equal(dms, repo):
    request = log(dms)
    assert repo.get_request(request.request_id) == request
    quote = issue(dms, request.request_id)
    assert repo.get_quote(request.request_id, quote.quote_id) == quote


def test_stale_write_conflicts(dms, repo):
    request = log(dms)
    first, second = repo.get_request(request.request_id), repo.get_request(request.request_id)
    first.status = RequestStatus.CANCELLED
    repo.transaction().update(first, ["status"], where={"status": RequestStatus.OPEN}).commit()
    with pytest.raises(ConflictError):
        repo.transaction().update(second, ["status"], where={"status": RequestStatus.OPEN}).commit()


def test_update_requires_existing_item(dms, repo):
    request = log(dms)
    quote = issue(dms, request.request_id)
    job = dms.accept_quote(AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"))
    ghost = job.model_copy(update={"job_id": "missing"})
    with pytest.raises(ConflictError):
        repo.transaction().update(ghost, ["state"]).commit()


# races between commands; each loads before the other saves
def stale(repo, monkeypatch, request_id, quote_id=None):
    stale_request = repo.get_request(request_id)
    stale_quote = repo.get_quote(request_id, quote_id) if quote_id else None

    def use() -> None:
        monkeypatch.setattr(repo, "get_request", lambda _: stale_request)
        monkeypatch.setattr(repo, "get_quote", lambda *_: stale_quote)

    return use


def test_two_staff_issuing_first_quote_conflicts(dms, repo, monkeypatch):
    request = log(dms)
    use_stale = stale(repo, monkeypatch, request.request_id)
    issue(dms, request.request_id)
    use_stale()
    with pytest.raises(ConflictError):
        issue(dms, request.request_id)


def test_accept_after_cancel_conflicts(dms, repo, monkeypatch):
    request = log(dms)
    quote = issue(dms, request.request_id)
    use_stale = stale(repo, monkeypatch, request.request_id, quote.quote_id)
    dms.cancel_request(CancelRequest(request_id=request.request_id, by="staff-1"))
    use_stale()
    with pytest.raises(ConflictError):
        dms.accept_quote(AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"))
    monkeypatch.undo()
    assert repo.get_request(request.request_id).status is RequestStatus.CANCELLED


def test_update_writes_only_listed_fields(dms, repo, dynamodb):
    request = log(dms)
    quote = issue(dms, request.request_id)
    # something else adds an attribute the model doesn't have, e.g. an index key
    dynamodb.update_item(
        TableName=TABLE_NAME,
        Key=QUOTE.key_of(quote),
        UpdateExpression="SET gsi1pk = :v",
        ExpressionAttributeValues={":v": {"S": "CUSTOMER#cust-1"}},
    )
    dms.reject_quote(RejectQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"))
    item = dynamodb.get_item(TableName=TABLE_NAME, Key=QUOTE.key_of(quote))["Item"]
    assert item["status"]["S"] == "rejected" and item["responded_by"]["S"] == "cust-1"
    assert item["gsi1pk"]["S"] == "CUSTOMER#cust-1"  # a whole-item Put would have dropped this


def test_update_refuses_unknown_field(dms, repo):
    request = log(dms)
    with pytest.raises(ValueError, match="no fields"):
        repo.transaction().update(request, ["stauts"])


def test_concurrent_accept_creates_one_job(dms, repo, dynamodb, monkeypatch):
    request = log(dms)
    quote = issue(dms, request.request_id)
    command = AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1")

    # both acceptances load before either saves, as two simultaneous clicks would
    stale_request, stale_quote = (
        repo.get_request(request.request_id),
        repo.get_quote(request.request_id, quote.quote_id),
    )
    dms.accept_quote(command)
    monkeypatch.setattr(repo, "get_request", lambda _: stale_request)
    monkeypatch.setattr(repo, "get_quote", lambda *_: stale_quote)
    with pytest.raises(ConflictError):
        dms.accept_quote(command)

    jobs = dynamodb.scan(
        TableName=TABLE_NAME,
        FilterExpression="begins_with(pk, :job)",
        ExpressionAttributeValues={":job": {"S": "JOB#"}},
    )["Items"]
    assert len(jobs) == 1
    assert history(dynamodb, request.request_id).count("quote_accepted") == 1


# staff supersede a quote while the customer rejects it
def test_reject_after_supersede_conflicts(dms, repo, monkeypatch):
    request = log(dms)
    q1 = issue(dms, request.request_id)
    # the customer loads before staff save, so the domain can't see the change
    stale_request, stale_q1 = repo.get_request(request.request_id), repo.get_quote(request.request_id, q1.quote_id)
    issue(dms, request.request_id)  # supersedes q1
    monkeypatch.setattr(repo, "get_request", lambda _: stale_request)
    monkeypatch.setattr(repo, "get_quote", lambda *_: stale_q1)
    with pytest.raises(ConflictError):
        dms.reject_quote(RejectQuote(request_id=request.request_id, quote_id=q1.quote_id, customer_id="cust-1"))
    monkeypatch.undo()
    assert repo.get_quote(request.request_id, q1.quote_id).status is QuoteStatus.SUPERSEDED


def test_refused_command_saves_nothing(dms, dynamodb):
    request = log(dms)
    quote = issue(dms, request.request_id)
    late = DeliveryManagementSystem(dms.repo, clock=lambda: T + timedelta(days=2))  # past expiry
    with pytest.raises(DomainError, match="expired"):
        late.accept_quote(AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"))
    assert dms.repo.get_quote(request.request_id, quote.quote_id).status is QuoteStatus.PENDING
    assert history(dynamodb, request.request_id) == ["request_logged", "quote_issued"]


def test_only_owner_can_respond(dms):
    request = log(dms)
    quote = issue(dms, request.request_id)
    with pytest.raises(ForbiddenError):
        dms.accept_quote(
            AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="someone-else")
        )


def test_anonymous_request_cannot_be_accepted(dms):
    request = log(dms, customer_id=None)
    quote = issue(dms, request.request_id)
    with pytest.raises(ForbiddenError):
        dms.accept_quote(AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"))


def test_reject_and_revision(dms, repo, dynamodb):
    request = log(dms)
    q1 = issue(dms, request.request_id)
    dms.reject_quote(RejectQuote(request_id=request.request_id, quote_id=q1.quote_id, customer_id="cust-1"))
    q2 = issue(dms, request.request_id)
    dms.request_quote_revision(
        RequestQuoteRevision(request_id=request.request_id, quote_id=q2.quote_id, customer_id="cust-1")
    )
    assert repo.get_quote(request.request_id, q1.quote_id).status is QuoteStatus.SUPERSEDED
    assert repo.get_quote(request.request_id, q2.quote_id).status is QuoteStatus.REVISION_REQUESTED
    assert history(dynamodb, request.request_id)[-2:] == ["quote_issued", "quote_revision_requested"]


def test_cancel_then_refuse_quote(dms, repo):
    request = log(dms)
    dms.cancel_request(CancelRequest(request_id=request.request_id, by="cust-1"))
    assert repo.get_request(request.request_id).status is RequestStatus.CANCELLED
    with pytest.raises(DomainError):
        issue(dms, request.request_id)


def test_unknown_request(dms):
    with pytest.raises(NotFoundError):
        issue(dms, "nope")
