from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from swe.app.commands import (
    AcceptQuote,
    AdjustPayment,
    AllocateJob,
    CancelRequest,
    CloseJob,
    Command,
    CreateDeliveryJob,
    DeclareSlot,
    IssueQuote,
    LogRequest,
    ReallocateJob,
    RecordPayment,
    RejectQuote,
    RemoveSlot,
)
from swe.app.errors import ForbiddenError
from swe.app.staff_roster import Candidate, StaffRoster
from swe.app.user_directory import UserDirectory
from swe.domain.job import (
    Allocation,
    DeliveryJob,
    JobAllocated,
    JobStateName,
    Payment,
    PaymentAdjustment,
    PaymentMethod,
    Settlement,
)
from swe.domain.request import DeliveryRequest, Quote, QuoteAccepted, QuoteStatus, RequestStatus
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import AvailabilitySlot, User
from swe.repo import ConflictError, NotFoundError, Repository, Transaction

# held by SystemConfiguration in the design (A7)
QUOTE_VALID_FOR = timedelta(hours=24)

# what a customer's response changes on a quote
RESPONSE_FIELDS = ["status", "responded_by", "responded_at"]

# a business day for daily collection totals is a Melbourne one (S2)
BUSINESS_TZ = ZoneInfo("Australia/Melbourne")


# what one person collected on one day, split by method so cash on hand can be checked
# against the handover and card against the provider's settlement (QA3.6, Task 7 5a)
class CollectionTotals(BaseModel):
    staff_id: str
    day: date
    cash: Decimal
    card: Decimal
    payments: list[Payment]  # oldest first
    adjustments: list[PaymentAdjustment]  # oldest first


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

    # the job's settlement, or a new one owing the accepted price before its first payment
    def settlement(self, job: DeliveryJob) -> Settlement:
        try:
            return self.repo.get_settlement(job.job_id)
        except NotFoundError:
            return Settlement(job_id=job.job_id, amount_due=self.repo.get_quote(job.request_id, job.quote_id).price)

    # Task 7 (A2 Figure 7.4a, part A). Only the driver holding the job may record it. The
    # save fails if the job was reallocated, or another payment was saved, since loading
    def record_payment(self, command: RecordPayment) -> Payment:
        job = self.repo.get_job(command.job_id)
        if job.delivery_staff_id != command.by:
            raise ForbiddenError("only the job's allocated driver can record its payment")

        def previous() -> Payment | None:
            return self._previous(
                lambda: self.repo.get_payment(job.job_id, command.payment_id), command, ["outcome", "method", "amount"]
            )

        if (earlier := previous()) is not None:
            return earlier
        settlement = self.settlement(job)
        loaded_revision = settlement.revision
        loaded_job = {"state": job.state, "delivery_staff_id": job.delivery_staff_id}
        payment, recorded = job.record_payment(
            settlement,
            payment_id=command.payment_id,
            outcome=command.outcome,
            method=command.method,
            amount=command.amount,
            reason=command.reason,
            by=command.by,
            at=self.clock(),
        )
        tx = self.repo.transaction().check(job, where=loaded_job).create(payment).create(recorded)
        self._save_settlement(tx, settlement, loaded_revision)
        return self._commit_submission(tx, previous) or payment

    # Task 7 variant 4a (A2 Figure 7.4a, part B): office staff append a correction or a
    # late balance; the Payment itself is never changed (QA3.5)
    def adjust_payment(self, command: AdjustPayment) -> PaymentAdjustment:
        job = self.repo.get_job(command.job_id)
        payment = self.repo.get_payment(job.job_id, command.payment_id)

        def previous() -> PaymentAdjustment | None:
            return self._previous(
                lambda: self.repo.get_adjustment(job.job_id, command.adjustment_id),
                command,
                ["payment_id", "amount", "method"],
            )

        if (earlier := previous()) is not None:
            return earlier
        settlement = self.repo.get_settlement(job.job_id)  # saved with the payment
        loaded_revision = settlement.revision
        adjustment, adjusted = job.adjust_payment(
            settlement,
            payment,
            adjustment_id=command.adjustment_id,
            amount=command.amount,
            method=command.method,
            provider_reference=command.provider_reference,
            reason=command.reason,
            by=command.by,
            at=self.clock(),
        )
        tx = self.repo.transaction().check(job, where={"state": job.state}).create(adjustment).create(adjusted)
        self._save_settlement(tx, settlement, loaded_revision)
        return self._commit_submission(tx, previous) or adjustment

    # A2 StaffMember: confirm closure once the job is delivered, its payment resolved and
    # no issue remains. Fails if a payment or adjustment was saved since loading
    def close_job(self, command: CloseJob) -> DeliveryJob:
        job = self.repo.get_job(command.job_id)
        settlement = self.settlement(job)
        progress = self.repo.get_execution_progress(job.job_id)
        loaded_state = job.state
        closed = job.close(
            settlement, issue_open=bool(progress and progress.open_issue_id), by=command.by, at=self.clock()
        )
        (
            self.repo.transaction()
            .update(job, ["state"], where={"state": loaded_state})
            .check(settlement, where={"revision": settlement.revision})
            .create(closed)
            .commit()
        )
        return job

    # Task 7 variant 5a: one person's collections on one Melbourne day. An office staff
    # member's card balances are theirs, kept apart from the driver's (QA3.6)
    def collection_totals(self, staff_id: str, day: date) -> CollectionTotals:
        start = datetime.combine(day, time(), BUSINESS_TZ).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time(), BUSINESS_TZ).astimezone(UTC)
        payments, adjustments = self.repo.list_collections(staff_id, start, end)
        totals = dict.fromkeys(PaymentMethod, Decimal(0))
        for record in [*payments, *adjustments]:
            if record.method is not None:  # a refused payment collected nothing
                totals[record.method] += record.amount
        return CollectionTotals(
            staff_id=staff_id,
            day=day,
            cash=totals[PaymentMethod.CASH],
            card=totals[PaymentMethod.CARD],
            payments=payments,
            adjustments=adjustments,
        )

    # the first save creates the settlement; later ones only succeed if nobody else has
    # saved it since it was loaded, so two payments can't both be taken against one balance
    def _save_settlement(self, tx: Transaction, settlement: Settlement, loaded_revision: int) -> None:
        if loaded_revision == 0:
            tx.create(settlement)
        else:
            tx.update(settlement, ["net_collected", "revision"], where={"revision": loaded_revision})

    # what an earlier submission with this id recorded, so a retry returns it rather than
    # recording it again. Reusing an id for different details is refused
    def _previous(self, load: Callable, command: Command, fields: list[str]):
        try:
            record = load()
        except NotFoundError:
            return None
        if record.created_by != command.by or any(getattr(record, f) != getattr(command, f) for f in fields):
            raise ConflictError("that submission was already used for different details")
        return record

    # None once committed; if it conflicted because a retry of the same submission got
    # there first, that one's record
    def _commit_submission(self, tx: Transaction, previous: Callable):
        try:
            tx.commit()
        except ConflictError:
            earlier = previous()
            if earlier is None:
                raise
            return earlier
        return None

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
