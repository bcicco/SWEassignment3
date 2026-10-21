# events raised by DeliveryJob (§4.5). They go in the job's request's history
from decimal import Decimal
from typing import Literal

from swe.domain.job.payment import PaymentMethod, PaymentOutcome
from swe.domain.shared.history_event import HistoryEvent


class JobCreated(HistoryEvent):
    event_type: Literal["job_created"] = "job_created"
    job_id: str


# outstanding is what's still owed afterwards; anything but 0 is flagged to office staff (QA3.4)
class PaymentRecorded(HistoryEvent):
    event_type: Literal["payment_recorded"] = "payment_recorded"
    job_id: str
    payment_id: str
    outcome: PaymentOutcome
    method: PaymentMethod | None = None
    amount: Decimal
    amount_due: Decimal
    outstanding: Decimal


class PaymentAdjusted(HistoryEvent):
    event_type: Literal["payment_adjusted"] = "payment_adjusted"
    job_id: str
    adjustment_id: str
    payment_id: str
    amount: Decimal
    method: PaymentMethod
    outstanding: Decimal


class JobClosed(HistoryEvent):
    event_type: Literal["job_closed"] = "job_closed"
    job_id: str


# a first allocation, or a reallocation when previous_delivery_staff_id is set
class JobAllocated(HistoryEvent):
    event_type: Literal["job_allocated"] = "job_allocated"
    job_id: str
    allocation_id: str
    delivery_staff_id: str
    previous_delivery_staff_id: str | None = None
    reason: str | None = None
