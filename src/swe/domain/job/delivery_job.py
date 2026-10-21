from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.job.allocation import Allocation
from swe.domain.job.events import JobAllocated, JobClosed, JobCreated, PaymentAdjusted, PaymentRecorded
from swe.domain.job.payment import Payment, PaymentAdjustment, PaymentMethod, PaymentOutcome, Settlement
from swe.domain.job.state import JobState, JobStateName
from swe.domain.shared.errors import DomainError
from swe.domain.shared.ids import new_id, now


class DeliveryJob(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    job_id: str = Field(default_factory=new_id, frozen=True)
    request_id: str = Field(frozen=True)
    quote_id: str = Field(frozen=True)
    customer_id: str = Field(frozen=True)  # copied from the request so a customer can list their jobs
    created_at: datetime = Field(default_factory=now, frozen=True)
    state: JobStateName = JobStateName.UNALLOCATED  # the current JobState's name; change it only through enter()
    # the active Allocation (A8), copied here so a driver's jobs can be listed and the
    # repo can lock on it. Earlier Allocations stay as their own records
    allocation_id: str | None = None
    delivery_staff_id: str | None = None

    # the one unallocated job for an accepted quote, with the id chosen at acceptance
    @classmethod
    def create(
        cls, *, job_id: str, request_id: str, quote_id: str, customer_id: str, at: datetime | None = None
    ) -> tuple["DeliveryJob", JobCreated]:
        at = at or now()
        job = cls(job_id=job_id, request_id=request_id, quote_id=quote_id, customer_id=customer_id, created_at=at)
        return job, JobCreated(request_id=request_id, job_id=job_id, created_at=at)

    # the lifecycle state that decides which actions are allowed
    @property
    def current_state(self) -> JobState:
        return JobState.for_name(self.state)

    # moves to the successor the current state returned for an accepted action
    def enter(self, successor: JobState) -> None:
        self.state = successor.name

    # Task 1 subtask 3. The current state decides whether it's allowed: a job that's
    # already allocated is refused (variant 3a) and must be reallocated instead
    def allocate(self, delivery_staff_id: str, by: str, at: datetime | None = None) -> tuple[Allocation, JobAllocated]:
        if self.delivery_staff_id is not None:
            raise DomainError(f"job is already allocated to {self.delivery_staff_id}; reallocate it instead")
        return self._assign(self.current_state.allocate(), delivery_staff_id, by, reason=None, at=at)

    # Task 1 subtask 5. Keeps the job at its current stage, e.g. still in transit (5b)
    def reallocate(
        self, delivery_staff_id: str, reason: str, by: str, at: datetime | None = None
    ) -> tuple[Allocation, JobAllocated]:
        successor = self.current_state.reallocate()
        if delivery_staff_id == self.delivery_staff_id:
            raise DomainError(f"job is already allocated to {delivery_staff_id}")
        return self._assign(successor, delivery_staff_id, by, reason=reason, at=at)

    # Task 7 subtasks 1-4 (A2 Figure 7.4b). The current state decides whether money can be
    # taken at this stage, Payment checks the outcome against what's due, and Settlement
    # adds it to what's been collected
    def record_payment(
        self,
        settlement: Settlement,
        *,
        payment_id: str,
        outcome: PaymentOutcome,
        method: PaymentMethod | None,
        amount: Decimal,
        reason: str | None,
        by: str,
        at: datetime,
    ) -> tuple[Payment, PaymentRecorded]:
        self.enter(self.current_state.record_payment())
        payment = Payment(
            id=payment_id,
            job_id=self.job_id,
            quote_id=self.quote_id,
            outcome=outcome,
            method=method,
            amount_due=settlement.due(),
            amount=amount,
            reason=reason,
            created_by=by,
            created_at=at,
        )
        settlement.apply_payment(payment)
        return payment, PaymentRecorded(
            request_id=self.request_id,
            job_id=self.job_id,
            payment_id=payment.id,
            outcome=payment.outcome,
            method=payment.method,
            amount=payment.amount,
            amount_due=payment.amount_due,
            outstanding=settlement.outstanding,
            created_by=by,
            created_at=at,
        )

    # Task 7 variant 4a (A2 Figure 7.4c): office staff correct or top up a Payment, which
    # itself is never changed
    def adjust_payment(
        self,
        settlement: Settlement,
        payment: Payment,
        *,
        adjustment_id: str,
        amount: Decimal,
        method: PaymentMethod,
        provider_reference: str | None,
        reason: str,
        by: str,
        at: datetime,
    ) -> tuple[PaymentAdjustment, PaymentAdjusted]:
        self.enter(self.current_state.record_payment())
        if payment.job_id != self.job_id:
            raise DomainError("that payment belongs to another job")
        adjustment = PaymentAdjustment(
            id=adjustment_id,
            job_id=self.job_id,
            payment_id=payment.id,
            amount=amount,
            method=method,
            provider_reference=provider_reference,
            reason=reason,
            created_by=by,
            created_at=at,
        )
        settlement.apply_adjustment(adjustment)
        return adjustment, PaymentAdjusted(
            request_id=self.request_id,
            job_id=self.job_id,
            adjustment_id=adjustment.id,
            payment_id=payment.id,
            amount=adjustment.amount,
            method=adjustment.method,
            outstanding=settlement.outstanding,
            created_by=by,
            created_at=at,
        )

    # only a Delivered job whose payment is resolved and has no open issue closes (A18)
    def close(self, settlement: Settlement, *, issue_open: bool, by: str, at: datetime) -> JobClosed:
        self.enter(self.current_state.close(payment_resolved=settlement.resolved, issue_open=issue_open))
        return JobClosed(request_id=self.request_id, job_id=self.job_id, created_by=by, created_at=at)

    def _assign(
        self, successor: JobState, delivery_staff_id: str, by: str, reason: str | None, at: datetime | None
    ) -> tuple[Allocation, JobAllocated]:
        at = at or now()
        # built before anything changes, so a refused allocation leaves the job as it was
        allocation = Allocation(
            job_id=self.job_id,
            delivery_staff_id=delivery_staff_id,
            replaces=self.allocation_id,
            reason=reason,
            created_by=by,
            created_at=at,
        )
        previous = self.delivery_staff_id
        self.enter(successor)
        self.allocation_id, self.delivery_staff_id = allocation.id, delivery_staff_id
        return allocation, JobAllocated(
            request_id=self.request_id,
            job_id=self.job_id,
            allocation_id=allocation.id,
            delivery_staff_id=delivery_staff_id,
            previous_delivery_staff_id=previous,
            reason=reason,
            created_by=by,
            created_at=at,
        )
