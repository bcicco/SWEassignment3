from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from swe.domain.shared.ids import new_id, now


# stored so the matching JobState class can be rebuilt on load;
# only JobState transitions should change it
class JobStateName(str, Enum):
    UNALLOCATED = "unallocated"
    ALLOCATED = "allocated"
    IN_TRANSIT = "in_transit"
    ON_HOLD = "on_hold"
    DELIVERED = "delivered"
    CLOSED = "closed"


class DeliveryJob(BaseModel):
    job_id: str = Field(default_factory = new_id, frozen = True)
    request_id: str = Field(frozen = True)
    quote_id: str = Field(frozen = True)
    created_at: datetime = Field(default_factory = now, frozen = True)
    state: JobStateName = JobStateName.UNALLOCATED
