# what callers (the web client, later the phone app) ask the system to do. Each is
# handled by the matching DeliveryManagementSystem method
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.shared import Address, Parcel


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
