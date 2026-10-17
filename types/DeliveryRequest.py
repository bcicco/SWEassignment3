from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from DeliveryJob import DeliveryJob
from HistoryEvent import EventType, HistoryEvent
from Quote import Quote, QuoteStatus
from shared.Address import Address
from shared.Parcel import Parcel
from shared.errors import DomainError
from shared.ids import new_id, now


class RequestStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


# quotes and history events are separate items in this request's partition, so
# methods return the events they produce for the caller to persist
class DeliveryRequest(BaseModel): 
    model_config = ConfigDict(validate_assignment = True)
    request_id: str = Field(default_factory = new_id, frozen = True)
    created_at: datetime = Field(default_factory = now, frozen = True)
    customer_id: str | None = Field(default = None, frozen = True) # None for anonymous requests (A9)
    logged_by: str | None = Field(default = None, frozen = True) # office staff logging for a caller (Task 5)
    contact_name: str = Field(min_length = 1, frozen = True)
    contact_phone: str = Field(min_length = 1, frozen = True)
    parcels: list[Parcel] = Field(min_length = 1, frozen = True) # A5
    pickup_address: Address = Field(frozen = True)
    dropoff_address: Address = Field(frozen = True)
    status: RequestStatus = RequestStatus.OPEN
    current_quote_id: str | None = None # A6: at most one live quote

    @model_validator(mode = "after")
    def _addresses_differ(self) -> "DeliveryRequest":
        if self.pickup_address == self.dropoff_address:
            raise ValueError("pickup and dropoff addresses must differ")
        return self

    @computed_field
    @property
    def pk(self) -> str:
        return f"REQUEST#{self.request_id}"

    @computed_field
    @property
    def sk(self) -> str:
        return "METADATA"

    @classmethod
    def log(cls, **details) -> tuple["DeliveryRequest", HistoryEvent]:
        request = cls(**details)
        actor = request.customer_id or request.logged_by
        return request, request._event(EventType.REQUEST_LOGGED, actor, request.created_at)

    def _event(self, event_type: EventType, by: str | None, at: datetime, reference_id: str | None = None) -> HistoryEvent:
        return HistoryEvent(
            request_id = self.request_id,
            event_type = event_type,
            reference_id = reference_id,
            created_by = by,
            created_at = at,
        )

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
    ) -> tuple[Quote, list[HistoryEvent]]:
        at = at or now()
        self._ensure_open()
        if self.current_quote_id is not None:
            if previous is None:
                raise DomainError("the current quote must be passed in to be superseded")
            self._ensure_current(previous)
        # build the new quote first so a validation failure changes nothing
        quote = Quote(
            request_id = self.request_id,
            price = price,
            eta_pickup = eta_pickup,
            eta_dropoff = eta_dropoff,
            time_of_issue = at,
            expiry_time = at + valid_for,
            issued_by = issued_by,
        )
        events = []
        if previous is not None:
            previous.supersede()
            events.append(self._event(EventType.QUOTE_SUPERSEDED, issued_by, at, previous.quote_id))
        self.current_quote_id = quote.quote_id
        events.append(self._event(EventType.QUOTE_ISSUED, issued_by, at, quote.quote_id))
        return quote, events

    def accept_quote(self, quote: Quote, by: str, at: datetime | None = None) -> tuple[DeliveryJob, HistoryEvent]:
        at = at or now()
        self._ensure_open()
        self._ensure_current(quote)
        job = quote.accept(by, at)
        self.status = RequestStatus.ACCEPTED
        return job, self._event(EventType.QUOTE_ACCEPTED, by, at, quote.quote_id)

    def reject_quote(self, quote: Quote, by: str, at: datetime | None = None) -> HistoryEvent:
        at = at or now()
        self._ensure_open()
        self._ensure_current(quote)
        quote.reject(by, at)
        return self._event(EventType.QUOTE_REJECTED, by, at, quote.quote_id)

    def request_revision(self, quote: Quote, by: str, at: datetime | None = None) -> HistoryEvent:
        at = at or now()
        self._ensure_open()
        self._ensure_current(quote)
        quote.request_revision(by, at)
        return self._event(EventType.QUOTE_REVISION_REQUESTED, by, at, quote.quote_id)

    # only before acceptance; afterwards it's a DeliveryIssue (A3)
    def cancel(self, by: str | None, at: datetime | None = None) -> HistoryEvent:
        at = at or now()
        self._ensure_open()
        self.status = RequestStatus.CANCELLED
        return self._event(EventType.REQUEST_CANCELLED, by, at)
