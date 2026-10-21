# request and response bodies. Fields the server fills in (who is acting, which request
# the URL names) are left out, so a client can't set them
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Union

from pydantic import BaseModel, Field

import swe.domain  # noqa: F401  registers every HistoryEvent subclass before the union below is built
from swe.domain.job import (
    Allocation,
    DeliveryJob,
    Payment,
    PaymentAdjustment,
    PaymentMethod,
    PaymentOutcome,
    Settlement,
)
from swe.domain.request import DeliveryRequest, Quote
from swe.domain.shared import Address, HistoryEvent, Parcel


class NewRequest(BaseModel):
    # staff logging for a caller (Task 5) name the caller's account, or leave it out for
    # an anonymous request (A9); customers always log for themselves
    customer_id: str | None = None
    contact_name: str
    contact_phone: str
    parcels: list[Parcel] = Field(min_length=1)
    pickup_address: Address
    dropoff_address: Address


# a driver declares slots for themselves
class NewSlot(BaseModel):
    window: tuple[datetime, datetime]


class NewAllocation(BaseModel):
    delivery_staff_id: str


class NewReallocation(BaseModel):
    delivery_staff_id: str
    reason: str


class NewQuote(BaseModel):
    price: Decimal
    eta_pickup: tuple[datetime, datetime]
    eta_dropoff: tuple[datetime, datetime]


# the client picks payment_id and adjustment_id (e.g. a UUID) and keeps it for a retry, so a
# payment whose confirmation was lost isn't recorded twice
class NewPayment(BaseModel):
    payment_id: str
    outcome: PaymentOutcome
    method: PaymentMethod | None = None
    amount: Decimal = Decimal(0)  # left out for a declined or refused payment
    reason: str | None = None


class NewAdjustment(BaseModel):
    adjustment_id: str
    amount: Decimal
    method: PaymentMethod
    provider_reference: str | None = None
    reason: str


class PaymentDetail(BaseModel):
    settlement: Settlement
    payments: list[Payment]  # oldest first
    adjustments: list[PaymentAdjustment]  # oldest first


# any registered event, told apart by event_type, so each keeps its own fields in the
# response and in the OpenAPI schema the React client is generated from
AnyHistoryEvent = Annotated[Union[tuple(HistoryEvent.registry.values())], Field(discriminator="event_type")]  # noqa: UP007


class RequestDetail(BaseModel):
    request: DeliveryRequest
    quotes: list[Quote]  # newest first
    history: list[AnyHistoryEvent]  # oldest first


# a job with the request it delivers, for listing
class JobSummary(BaseModel):
    job: DeliveryJob
    request: DeliveryRequest


class JobDetail(JobSummary):
    quote: Quote  # the accepted terms
    allocations: list[Allocation]  # oldest first; the last is active
