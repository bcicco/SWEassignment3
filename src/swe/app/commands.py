# what callers (the web client, later the phone app) ask the system to do. Each is
# handled by the matching DeliveryManagementSystem method
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.job import PaymentMethod, PaymentOutcome
from swe.domain.shared import Address, Parcel

# chosen by the client, so a retried submission is recognised instead of recorded twice
SubmissionId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")]


class Command(BaseModel):
    model_config = ConfigDict(frozen=True)


# Task 5. customer_id is None for an anonymous request (A9); logged_by is set when
# office staff log it for a caller
class LogRequest(Command):
    customer_id: str | None = None
    logged_by: str | None = None
    contact_name: str
    contact_phone: str
    parcels: list[Parcel] = Field(min_length=1)
    pickup_address: Address
    dropoff_address: Address


# Task 3. Issuing a new quote supersedes the current one (A6). The price is entered
# for now; PricingPolicy will supply it
class IssueQuote(Command):
    request_id: str
    staff_id: str
    price: Decimal
    eta_pickup: tuple[datetime, datetime]
    eta_dropoff: tuple[datetime, datetime]


# Task 3 customer responses; only the request's own customer may respond
class AcceptQuote(Command):
    request_id: str
    quote_id: str
    customer_id: str


class RejectQuote(Command):
    request_id: str
    quote_id: str
    customer_id: str


# raised by the create-delivery-job handler from QuoteAccepted, which chose the job id
class CreateDeliveryJob(Command):
    job_id: str
    request_id: str
    quote_id: str
    customer_id: str


# A3: before acceptance only
class CancelRequest(Command):
    request_id: str
    by: str | None = None


# Task 8: a driver declaring or removing a period they can work. Slots are never
# edited; a change is a removal and a new declaration
class DeclareSlot(Command):
    delivery_staff_id: str
    window: tuple[datetime, datetime]
    by: str


class RemoveSlot(Command):
    delivery_staff_id: str
    slot_id: str
    by: str


# Task 1: office staff assigning a job to a driver, or moving it to another (subtask 5)
class AllocateJob(Command):
    job_id: str
    delivery_staff_id: str
    by: str


class ReallocateJob(Command):
    job_id: str
    delivery_staff_id: str
    reason: str = Field(min_length=1)
    by: str


# Task 7: the allocated driver records what happened when collecting payment
class RecordPayment(Command):
    job_id: str
    payment_id: SubmissionId
    outcome: PaymentOutcome
    method: PaymentMethod | None = None
    amount: Decimal
    reason: str | None = None
    by: str


# Task 7 variant 4a: office staff correct a payment or record a late balance
class AdjustPayment(Command):
    job_id: str
    payment_id: str
    adjustment_id: SubmissionId
    amount: Decimal
    method: PaymentMethod
    provider_reference: str | None = None
    reason: str
    by: str


# office staff confirm a delivered, paid job is finished (A18)
class CloseJob(Command):
    job_id: str
    by: str
