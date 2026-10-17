from collections.abc import Callable
from datetime import datetime, timedelta

from swe.app.commands import (
    AcceptQuote,
    CancelRequest,
    IssueQuote,
    LogRequest,
    RejectQuote,
    RequestQuoteRevision,
)
from swe.app.errors import ForbiddenError
from swe.domain.job import DeliveryJob
from swe.domain.request import DeliveryRequest, Quote, QuoteStatus, RequestStatus
from swe.domain.shared.ids import now
from swe.repo import Repository

# held by SystemConfiguration in the design (A7)
QUOTE_VALID_FOR = timedelta(hours=24)

# what a customer's response changes on a quote
RESPONSE_FIELDS = ["status", "responded_by", "responded_at"]


# The single entry point for commands (§4.2). Each method loads what it needs, lets
# the domain objects decide, then saves every change in one transaction. Business
# rules stay in the domain; this only coordinates.
#
# Errors: DomainError (rule refused), ForbiddenError, NotFoundError, ConflictError
# (someone else changed it first; reload and retry)
class DeliveryManagementSystem:
    def __init__(
        self,
        repo: Repository | None = None,
        quote_valid_for: timedelta = QUOTE_VALID_FOR,
        clock: Callable[[], datetime] = now,
    ):
        self.repo = repo or Repository()
        self.quote_valid_for = quote_valid_for
        self.clock = clock

    def log_request(self, command: LogRequest) -> DeliveryRequest:
        request, logged = DeliveryRequest.log(**command.model_dump(), created_at=self.clock())
        self.repo.transaction().create(request).create(logged).commit()
        return request

    def issue_quote(self, command: IssueQuote) -> Quote:
        request = self.repo.get_request(command.request_id)
        previous = (
            self.repo.get_quote(request.request_id, request.current_quote_id) if request.current_quote_id else None
        )
        previous_status = previous.status if previous else None  # superseding changes it
        loaded_quote_id = request.current_quote_id
        quote, issued = request.issue_quote(
            price=command.price,
            eta_pickup=command.eta_pickup,
            eta_dropoff=command.eta_dropoff,
            valid_for=self.quote_valid_for,
            issued_by=command.staff_id,
            previous=previous,
            at=self.clock(),
        )
        tx = (
            self.repo.transaction()
            .update(
                request,
                ["current_quote_id"],
                where={"status": RequestStatus.OPEN, "current_quote_id": loaded_quote_id},
            )
            .create(quote)
            .create(issued)
        )
        if previous is not None:
            tx.update(previous, ["status"], where={"status": previous_status})
        tx.commit()
        return quote

    def accept_quote(self, command: AcceptQuote) -> DeliveryJob:
        request, quote = self._load_for_response(command.request_id, command.quote_id, command.customer_id)
        job, accepted = request.accept_quote(quote, by=command.customer_id, at=self.clock())
        (
            self.repo.transaction()
            .update(request, ["status"], where={"status": RequestStatus.OPEN})
            .update(quote, RESPONSE_FIELDS, where={"status": QuoteStatus.PENDING})
            .create(job)
            .create(accepted)
            .commit()
        )
        return job

    def reject_quote(self, command: RejectQuote) -> Quote:
        request, quote = self._load_for_response(command.request_id, command.quote_id, command.customer_id)
        rejected = request.reject_quote(quote, by=command.customer_id, at=self.clock())
        (
            self.repo.transaction()
            .update(quote, RESPONSE_FIELDS, where={"status": QuoteStatus.PENDING})
            .create(rejected)
            .commit()
        )
        return quote

    def request_quote_revision(self, command: RequestQuoteRevision) -> Quote:
        request, quote = self._load_for_response(command.request_id, command.quote_id, command.customer_id)
        requested = request.request_revision(quote, by=command.customer_id, at=self.clock())
        (
            self.repo.transaction()
            .update(quote, RESPONSE_FIELDS, where={"status": QuoteStatus.PENDING})
            .create(requested)
            .commit()
        )
        return quote

    def cancel_request(self, command: CancelRequest) -> DeliveryRequest:
        request = self.repo.get_request(command.request_id)
        cancelled = request.cancel(by=command.by, at=self.clock())
        (
            self.repo.transaction()
            .update(request, ["status"], where={"status": RequestStatus.OPEN})
            .create(cancelled)
            .commit()
        )
        return request

    # ownership stands in for AccessPolicy until roles exist (QA3.2). A customer
    # needs an account to respond, so anonymous requests can't be accepted yet (A9)
    def _load_for_response(self, request_id: str, quote_id: str, customer_id: str) -> tuple[DeliveryRequest, Quote]:
        request = self.repo.get_request(request_id)
        if request.customer_id is None or request.customer_id != customer_id:
            raise ForbiddenError("only the request's customer can respond to its quote")
        return request, self.repo.get_quote(request_id, quote_id)
