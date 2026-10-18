from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from swe.domain.job.delivery_job import DeliveryJob
from swe.domain.shared.errors import DomainError
from swe.domain.shared.ids import new_id, now


class QuoteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


## documented, class was meant to immutable but also had to record accepted or not
# -> individual fields immutable
class Quote(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    request_id: str = Field(frozen=True)
    quote_id: str = Field(default_factory=new_id, frozen=True)
    price: Decimal = Field(gt=0, frozen=True)  # AUD (S1)
    eta_pickup: tuple[datetime, datetime] = Field(frozen=True)
    eta_dropoff: tuple[datetime, datetime] = Field(frozen=True)
    time_of_issue: datetime = Field(default_factory=now, frozen=True)
    expiry_time: datetime = Field(frozen=True)
    issued_by: str = Field(frozen=True)
    status: QuoteStatus = QuoteStatus.PENDING  # never returns to an earlier value, so the repo locks on it
    responded_by: str | None = None
    responded_at: datetime | None = None

    @field_validator("eta_pickup", "eta_dropoff")
    @classmethod
    def _window_in_order(cls, window: tuple[datetime, datetime]) -> tuple[datetime, datetime]:
        if window[1] <= window[0]:
            raise ValueError("window must end after it starts")
        return window

    def is_expired(self, at: datetime) -> bool:
        return at >= self.expiry_time

    def _ensure_respondable(self, at: datetime) -> None:
        if self.status is not QuoteStatus.PENDING:
            raise DomainError(f"quote is {self.status.value}, not pending")
        if self.is_expired(at):
            raise DomainError("quote has expired")

    def _record_response(self, status: QuoteStatus, by: str, at: datetime) -> None:
        self.status = status
        self.responded_by = by
        self.responded_at = at

    # creates the one unallocated job from the accepted terms; only the request's own
    # customer may accept, so they own the job
    def accept(self, by: str, at: datetime) -> DeliveryJob:
        self._ensure_respondable(at)
        self._record_response(QuoteStatus.ACCEPTED, by, at)
        return DeliveryJob(request_id=self.request_id, quote_id=self.quote_id, customer_id=by, created_at=at)

    def reject(self, by: str, at: datetime) -> None:
        self._ensure_respondable(at)
        self._record_response(QuoteStatus.REJECTED, by, at)

    # an expired or answered quote can still be replaced; only an accepted one can't
    def supersede(self) -> None:
        if self.status is QuoteStatus.ACCEPTED:
            raise DomainError("an accepted quote cannot be superseded")
        self.status = QuoteStatus.SUPERSEDED
