from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from swe.domain.job.events import JobCreated
from swe.domain.shared.ids import new_id, now


# stored so the matching JobState class can be rebuilt on load;
# only JobState transitions should change it
class JobStateName(StrEnum):
    UNALLOCATED = "unallocated"
    ALLOCATED = "allocated"
    IN_TRANSIT = "in_transit"
    ON_HOLD = "on_hold"
    DELIVERED = "delivered"
    CLOSED = "closed"


class DeliveryJob(BaseModel):
    job_id: str = Field(default_factory=new_id, frozen=True)
    request_id: str = Field(frozen=True)
    quote_id: str = Field(frozen=True)
    customer_id: str = Field(frozen=True)  # copied from the request so a customer can list their jobs
    created_at: datetime = Field(default_factory=now, frozen=True)
    state: JobStateName = JobStateName.UNALLOCATED

    # the one unallocated job for an accepted quote, with the id chosen at acceptance
    @classmethod
    def create(
        cls, *, job_id: str, request_id: str, quote_id: str, customer_id: str, at: datetime | None = None
    ) -> tuple["DeliveryJob", JobCreated]:
        at = at or now()
        job = cls(job_id=job_id, request_id=request_id, quote_id=quote_id, customer_id=customer_id, created_at=at)
        return job, JobCreated(request_id=request_id, job_id=job_id, created_at=at)
