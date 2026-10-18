from pydantic import model_validator

from swe.domain.shared.base import Record


# One assignment of a job to a driver (§4.9). Never edited: a reallocation is a new
# Allocation that names the one it replaces, so the trail is kept (Task 1 5b, A8).
# created_by is the office staff member who allocated it
class Allocation(Record):
    job_id: str
    delivery_staff_id: str
    replaces: str | None = None  # the previous Allocation's id, for a reallocation
    reason: str | None = None  # why it was reallocated

    @model_validator(mode="after")
    def _reallocation_has_reason(self) -> "Allocation":
        if self.replaces is not None and not (self.reason and self.reason.strip()):
            raise ValueError("a reallocation needs a reason")
        return self
