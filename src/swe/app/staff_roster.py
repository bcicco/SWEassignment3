from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel

from swe.app.commands import DeclareSlot, RemoveSlot
from swe.app.user_directory import UserDirectory
from swe.domain.job import JobStateName
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import AvailabilitySlot, DeliveryStaff
from swe.repo import NotFoundError, Repository

# jobs still taking up a driver's time; delivered and closed ones don't count
ACTIVE_STATES = {JobStateName.ALLOCATED, JobStateName.IN_TRANSIT, JobStateName.ON_HOLD}


# a driver free for a pickup window, with how busy they are (Task 1 2b)
class Candidate(BaseModel):
    driver: DeliveryStaff
    load: int


# "Who can take this job?" (§4.6): each driver's availability, kept apart from the
# accounts themselves (UserDirectory) so neither grows large.
#
# A driver only declares their own slots, so two overlapping declarations made at the
# same moment aren't guarded against; at this volume (A13) that's accepted
class StaffRoster:
    def __init__(self, repo: Repository, users: UserDirectory, clock: Callable[[], datetime] = now):
        self.repo = repo
        self.users = users
        self.clock = clock

    def slots_of(self, delivery_staff_id: str) -> list[AvailabilitySlot]:
        return self.repo.list_slots(delivery_staff_id)

    # Task 8 subtask 1; an overlapping slot is refused (variant 1a)
    def declare_slot(self, command: DeclareSlot) -> AvailabilitySlot:
        if not isinstance(self.users.find(command.delivery_staff_id), DeliveryStaff):
            raise DomainError("only delivery staff declare availability")
        slot = AvailabilitySlot(
            delivery_staff_id=command.delivery_staff_id,
            window=command.window,
            created_by=command.by,
            created_at=self.clock(),
        )
        for existing in self.slots_of(command.delivery_staff_id):
            if existing.overlaps(slot):
                start, end = (t.isoformat() for t in existing.window)
                raise DomainError(f"overlaps the slot from {start} to {end}")
        self.repo.transaction().create(slot).commit()
        return slot

    # Task 8 subtask 2. TODO with allocation: jobs already allocated to the driver in
    # this window go to Dispatcher to be flagged for reallocation
    def remove_slot(self, command: RemoveSlot) -> AvailabilitySlot:
        slot = next((s for s in self.slots_of(command.delivery_staff_id) if s.id == command.slot_id), None)
        if slot is None:
            raise NotFoundError(f"no slot {command.slot_id} for {command.delivery_staff_id}")
        self.repo.transaction().delete(slot).commit()
        return slot

    # drivers with a slot covering the whole pickup window (Task 1 subtask 2). A driver
    # with no slots is never a candidate (Task 8 3a)
    def available_for(self, pickup_window: tuple[datetime, datetime]) -> list[DeliveryStaff]:
        return [driver for driver in self.users.list_delivery_staff() if self._covers(driver.user_id, pickup_window)]

    # checked again just before an allocation is saved (A2 Figure 7.2b, step 25)
    def is_available(self, delivery_staff_id: str, pickup_window: tuple[datetime, datetime]) -> bool:
        return isinstance(self.users.find(delivery_staff_id), DeliveryStaff) and self._covers(
            delivery_staff_id, pickup_window
        )

    # how many unfinished jobs the driver holds. Simpler than the design's "allocations
    # for the period": every unfinished job counts, whatever its day
    def load_of(self, delivery_staff_id: str) -> int:
        return sum(job.state in ACTIVE_STATES for job in self.repo.list_driver_jobs(delivery_staff_id))

    # available drivers, least busy first, so availability is never just yes or no (2b)
    def candidates_for(self, pickup_window: tuple[datetime, datetime]) -> list[Candidate]:
        candidates = [Candidate(driver=d, load=self.load_of(d.user_id)) for d in self.available_for(pickup_window)]
        return sorted(candidates, key=lambda c: (c.load, c.driver.user_id))

    def _covers(self, delivery_staff_id: str, pickup_window: tuple[datetime, datetime]) -> bool:
        return any(slot.covers(pickup_window) for slot in self.slots_of(delivery_staff_id))
