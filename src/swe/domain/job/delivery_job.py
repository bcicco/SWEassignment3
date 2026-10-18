from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.job.events import JobCreated
from swe.domain.job.state import JobState, JobStateName
from swe.domain.shared.ids import new_id, now


class DeliveryJob(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    job_id: str = Field(default_factory=new_id, frozen=True)
    request_id: str = Field(frozen=True)
    quote_id: str = Field(frozen=True)
    customer_id: str = Field(frozen=True)  # copied from the request so a customer can list their jobs
    created_at: datetime = Field(default_factory=now, frozen=True)
    state: JobStateName = JobStateName.UNALLOCATED  # the current JobState's name; change it only through enter()

    # the one unallocated job for an accepted quote, with the id chosen at acceptance
    @classmethod
    def create(
        cls, *, job_id: str, request_id: str, quote_id: str, customer_id: str, at: datetime | None = None
    ) -> tuple["DeliveryJob", JobCreated]:
        at = at or now()
        job = cls(job_id=job_id, request_id=request_id, quote_id=quote_id, customer_id=customer_id, created_at=at)
        return job, JobCreated(request_id=request_id, job_id=job_id, created_at=at)

    # the lifecycle state that decides which actions are allowed
    @property
    def current_state(self) -> JobState:
        return JobState.for_name(self.state)

    # moves to the successor the current state returned for an accepted action
    def enter(self, successor: JobState) -> None:
        self.state = successor.name
