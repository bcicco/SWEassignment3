from collections.abc import Callable
from datetime import datetime, timedelta

from swe.app.commands import (
    AcceptQuote,
    AllocateJob,
    CancelRequest,
    CreateDeliveryJob,
    DeclareSlot,
    IssueQuote,
    LogRequest,
    ReallocateJob,
    RejectQuote,
    RemoveSlot,
)
from swe.app.errors import ForbiddenError
from swe.app.staff_roster import Candidate, StaffRoster
from swe.app.user_directory import UserDirectory
from swe.domain.job import Allocation, DeliveryJob, JobAllocated, JobStateName
from swe.domain.request import DeliveryRequest, Quote, QuoteAccepted, QuoteStatus, RequestStatus
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import AvailabilitySlot, User
from swe.repo import ConflictError, NotFoundError, Repository

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
        users: UserDirectory | None = None,
        roster: StaffRoster | None = None,
        quote_valid_for: timedelta = QUOTE_VALID_FOR,
        clock: Callable[[], datetime] = now,
    ):
        self.repo = repo or Repository()
        self.quote_valid_for = quote_valid_for
        self.clock = clock
        self.users = users or UserDirectory(self.repo)
        self.roster = roster or StaffRoster(self.repo, self.users, clock)

    # the account behind an identity the platform authenticated (A11);
    # NotFoundError if there's none
    def identify(self, user_id: str) -> User:
        return self.users.find(user_id)

    def declare_slot(self, command: DeclareSlot) -> AvailabilitySlot:
        return self.roster.declare_slot(command)

    def remove_slot(self, command: RemoveSlot) -> AvailabilitySlot:
        return self.roster.remove_slot(command)

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

    # the job is created afterwards, from the QuoteAccepted event (create_delivery_job)
    def accept_quote(self, command: AcceptQuote) -> QuoteAccepted:
        request, quote = self._load_for_response(command.request_id, command.quote_id, command.customer_id)
        accepted = request.accept_quote(quote, by=command.customer_id, at=self.clock())
        (
            self.repo.transaction()
            .update(request, ["status"], where={"status": RequestStatus.OPEN})
            .update(quote, RESPONSE_FIELDS, where={"status": QuoteStatus.PENDING})
            .create(accepted)
            .commit()
        )
        return accepted

    # events can arrive more than once, so an existing job is returned rather than
    # created again; the conflict covers two deliveries racing each other
    def create_delivery_job(self, command: CreateDeliveryJob) -> DeliveryJob:
        try:
            return self.repo.get_job(command.job_id)
        except NotFoundError:
            pass
        job, created = DeliveryJob.create(**command.model_dump(), at=self.clock())
        try:
            self.repo.transaction().create(job).create(created).commit()
        except ConflictError:
            return self.repo.get_job(command.job_id)
        return job

    # drivers free for the job's committed pickup window, least busy first (Task 1
    # subtask 2). An empty list means the window must be renegotiated with the
    # customer (variant 2a)
    def job_candidates(self, job_id: str) -> list[Candidate]:
        return self.roster.candidates_for(self._pickup_window(self.repo.get_job(job_id)))

    # Task 1 subtask 3. The save only succeeds if the job is still unallocated, so two
    # staff allocating at once can't both win (variant 3a); the loser reloads and is
    # told who has it. This replaces the design's Dispatcher lock
    def allocate_job(self, command: AllocateJob) -> Allocation:
        job = self.repo.get_job(command.job_id)
        self._ensure_available(command.delivery_staff_id, job)
        allocation, allocated = job.allocate(command.delivery_staff_id, by=command.by, at=self.clock())
        self._save_allocation(
            job, allocation, allocated, where={"state": JobStateName.UNALLOCATED, "allocation_id": None}
        )
        return allocation

    # Task 1 subtask 5: the earlier Allocation is kept, and the job stays at its stage
    def reallocate_job(self, command: ReallocateJob) -> Allocation:
        job = self.repo.get_job(command.job_id)
        loaded = {"state": job.state, "allocation_id": job.allocation_id}
        self._ensure_available(command.delivery_staff_id, job)
        allocation, allocated = job.reallocate(
            command.delivery_staff_id, reason=command.reason, by=command.by, at=self.clock()
        )
        self._save_allocation(job, allocation, allocated, where=loaded)
        return allocation

    def _pickup_window(self, job: DeliveryJob) -> tuple[datetime, datetime]:
        return self.repo.get_quote(job.request_id, job.quote_id).eta_pickup

    def _ensure_available(self, delivery_staff_id: str, job: DeliveryJob) -> None:
        if not self.roster.is_available(delivery_staff_id, self._pickup_window(job)):
            raise DomainError(f"{delivery_staff_id} isn't available for the whole pickup window")

    def _save_allocation(self, job: DeliveryJob, allocation: Allocation, allocated: JobAllocated, where: dict) -> None:
        (
            self.repo.transaction()
            .update(job, ["state", "allocation_id", "delivery_staff_id"], where=where)
            .create(allocation)
            .create(allocated)
            .commit()
        )

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
