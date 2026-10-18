# events raised by DeliveryJob (§4.5). They go in the job's request's history
from typing import Literal

from swe.domain.shared.history_event import HistoryEvent


class JobCreated(HistoryEvent):
    event_type: Literal["job_created"] = "job_created"
    job_id: str


# a first allocation, or a reallocation when previous_delivery_staff_id is set
class JobAllocated(HistoryEvent):
    event_type: Literal["job_allocated"] = "job_allocated"
    job_id: str
    allocation_id: str
    delivery_staff_id: str
    previous_delivery_staff_id: str | None = None
    reason: str | None = None
