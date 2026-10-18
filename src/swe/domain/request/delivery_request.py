from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swe.domain.job.delivery_job import DeliveryJob
from swe.domain.request.events import (
    QuoteAccepted,
    QuoteIssued,
    QuoteRejected,
    RequestCancelled,
    RequestLogged,
)
from swe.domain.request.quote import Quote
from swe.domain.shared.address import Address
from swe.domain.shared.errors import DomainError
from swe.domain.shared.ids import new_id, now
from swe.domain.shared.parcel import Parcel


class RequestStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


# quotes and history events are separate items in this request's partition, so
# methods return the events they produce for the caller to persist
class DeliveryRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    request_id: str = Field(default_factory=new_id, frozen=True)
    created_at: datetime = Field(default_factory=now, frozen=True)
    customer_id: str | None = Field(default=None, frozen=True)  # None for anonymous requests (A9)
    logged_by: str | None = Field(default=None, frozen=True)  # office staff logging for a caller (Task 5)
    contact_name: str = Field(min_length=1, frozen=True)
    contact_phone: str = Field(min_length=1, frozen=True)
    parcels: list[Parcel] = Field(min_length=1, frozen=True)  # A5
    pickup_address: Address = Field(frozen=True)
    dropoff_address: Address = Field(frozen=True)
    status: RequestStatus = RequestStatus.OPEN  # only moves forward, so the repo locks on it
    current_quote_id: str | None = None  # A6: at most one live quote; a new id each time

    @model_validator(mode="after")
    def _addresses_differ(self) -> "DeliveryRequest":
        if self.pickup_address == self.dropoff_address:
            raise ValueError("pickup and dropoff addresses must differ")
        return self

    @classmethod
    def log(cls, **details) -> tuple["DeliveryRequest", RequestLogged]:
        request = cls(**details)
        event = RequestLogged(
            request_id=request.request_id,
            customer_id=request.customer_id,
            logged_by=request.logged_by,
            created_by=request.customer_id or request.logged_by,
            created_at=request.created_at,
        )
        return request, event

    def _ensure_open(self) -> None:
        if self.status is not RequestStatus.OPEN:
            raise DomainError(f"request is {self.status.value}")

    def _ensure_current(self, quote: Quote) -> None:
        if quote.request_id != self.request_id or quote.quote_id != self.current_quote_id:
            raise DomainError("quote is not the current quote for this request")

    # price comes from PricingPolicy and valid_for from SystemConfiguration (A7)
    def issue_quote(
        self,
        *,
        price: Decimal,
        eta_pickup: tuple[datetime, datetime],
        eta_dropoff: tuple[datetime, datetime],
        valid_for: timedelta,
        issued_by: str,
        previous: Quote | None,
        at: datetime | None = None,
    ) -> tuple[Quote, QuoteIssued]:
        at = at or now()
        self._ensure_open()
        if self.current_quote_id is not None:
            if previous is None:
                raise DomainError("the current quote must be passed in to be superseded")
            self._ensure_current(previous)
        # build the new quote first so a validation failure changes nothing
        quote = Quote(
            request_id=self.request_id,
            price=price,
            eta_pickup=eta_pickup,
            eta_dropoff=eta_dropoff,
            time_of_issue=at,
            expiry_time=at + valid_for,
            issued_by=issued_by,
        )
        if previous is not None:
            previous.supersede()
        self.current_quote_id = quote.quote_id
        return quote, QuoteIssued(
            request_id=self.request_id,
            quote_id=quote.quote_id,
            price=quote.price,
            expiry_time=quote.expiry_time,
            supersedes=previous.quote_id if previous else None,
            created_by=issued_by,
            created_at=at,
        )

    def accept_quote(self, quote: Quote, by: str, at: datetime | None = None) -> tuple[DeliveryJob, QuoteAccepted]:
        at = at or now()
        self._ensure_open()
        self._ensure_current(quote)
        job = quote.accept(by, at)
        self.status = RequestStatus.ACCEPTED
        return job, QuoteAccepted(
            request_id=self.request_id,
            quote_id=quote.quote_id,
            job_id=job.job_id,
            created_by=by,
            created_at=at,
        )

    def reject_quote(self, quote: Quote, by: str, at: datetime | None = None) -> QuoteRejected:
        at = at or now()
        self._ensure_open()
        self._ensure_current(quote)
        quote.reject(by, at)
        return QuoteRejected(request_id=self.request_id, quote_id=quote.quote_id, created_by=by, created_at=at)

    # only before acceptance; afterwards it's a DeliveryIssue (A3)
    def cancel(self, by: str | None, at: datetime | None = None) -> RequestCancelled:
        at = at or now()
        self._ensure_open()
        self.status = RequestStatus.CANCELLED
        return RequestCancelled(request_id=self.request_id, created_by=by, created_at=at)
