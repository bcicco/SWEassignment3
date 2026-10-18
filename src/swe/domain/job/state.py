# The job lifecycle as a State pattern (§5.2.1). DeliveryJob holds one current state
# and asks it whether an action is allowed; the state either refuses with a
# DomainError, leaving the job unchanged, or returns the state the job moves to.
#
# States hold no data, so the facts a decision needs (e.g. whether payment is
# resolved) are passed in by DeliveryJob, which gets them from its collaborators
from enum import StrEnum
from typing import ClassVar

from swe.domain.shared.errors import DomainError


# stored on the job so the matching JobState can be rebuilt on load
class JobStateName(StrEnum):
    UNALLOCATED = "unallocated"
    ALLOCATED = "allocated"
    IN_TRANSIT = "in_transit"
    ON_HOLD = "on_hold"
    DELIVERED = "delivered"
    CLOSED = "closed"


class JobState:
    registry: ClassVar[dict[JobStateName, type["JobState"]]] = {}
    name: ClassVar[JobStateName]

    # concrete states register themselves, so this class never lists them
    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        JobState.registry[cls.name] = cls

    @classmethod
    def for_name(cls, name: JobStateName) -> "JobState":
        return JobState.registry[JobStateName(name)]()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, JobState) and other.name is self.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def _refuse(self, action: str) -> DomainError:
        return DomainError(f"cannot {action} a job that is {self.name.value.replace('_', ' ')}")

    # every action is refused unless a concrete state permits it

    def allocate(self) -> "JobState":
        raise self._refuse("allocate")

    # a different driver; the stage the job is at doesn't change (§5.2.1)
    def reallocate(self) -> "JobState":
        raise self._refuse("reallocate")

    def record_pickup(self, *, succeeded: bool) -> "JobState":
        raise self._refuse("record a pickup for")

    # a successful delivery needs valid proof, which DeliveryAttempt checks first
    def record_delivery(self, *, succeeded: bool) -> "JobState":
        raise self._refuse("record a delivery for")

    # after office staff review the issue (A15)
    def resume(self, *, issue_addressed: bool, parcels_with_driver: bool) -> "JobState":
        raise self._refuse("resume")

    def record_payment(self) -> "JobState":
        raise self._refuse("record a payment for")

    def close(self, *, payment_resolved: bool, issue_open: bool) -> "JobState":
        raise self._refuse("close")


class Unallocated(JobState):
    name = JobStateName.UNALLOCATED

    def allocate(self) -> JobState:
        return Allocated()


# assigned to a driver, awaiting pickup or collection
class Allocated(JobState):
    name = JobStateName.ALLOCATED

    def reallocate(self) -> JobState:
        return self

    def record_pickup(self, *, succeeded: bool) -> JobState:
        return InTransit() if succeeded else OnHold()

    # a payment taken at collection isn't evidence of delivery
    def record_payment(self) -> JobState:
        return self


# the parcels are with the allocated driver
class InTransit(JobState):
    name = JobStateName.IN_TRANSIT

    # keeps the earlier pickup's attribution (Task 1 5b)
    def reallocate(self) -> JobState:
        return self

    def record_delivery(self, *, succeeded: bool) -> JobState:
        return Delivered() if succeeded else OnHold()

    def record_payment(self) -> JobState:
        return self


# stopped until an issue is dealt with; a new driver alone doesn't lift the hold
class OnHold(JobState):
    name = JobStateName.ON_HOLD

    def reallocate(self) -> JobState:
        return self

    def resume(self, *, issue_addressed: bool, parcels_with_driver: bool) -> JobState:
        if not issue_addressed:
            raise DomainError("the issue holding this job hasn't been addressed")
        # returned parcels must be collected again (A15)
        return InTransit() if parcels_with_driver else Allocated()

    def record_payment(self) -> JobState:
        return self


# handed over; may still need payment resolved before closing (A18)
class Delivered(JobState):
    name = JobStateName.DELIVERED

    def record_payment(self) -> JobState:
        return self

    def close(self, *, payment_resolved: bool, issue_open: bool) -> JobState:
        if not payment_resolved:
            raise DomainError("payment must be resolved before the job can close (Task 7 3b)")
        if issue_open:
            raise DomainError("an open issue must be resolved before the job can close")
        return Closed()


# the lifecycle has ended; every action is refused and the records stay for review
class Closed(JobState):
    name = JobStateName.CLOSED
