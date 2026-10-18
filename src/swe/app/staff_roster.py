from collections.abc import Callable
from datetime import datetime

from swe.app.commands import DeclareSlot, RemoveSlot
from swe.app.user_directory import UserDirectory
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import AvailabilitySlot, DeliveryStaff
from swe.repo import NotFoundError, Repository


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
    # with no slots is never a candidate (Task 8 3a). TODO with allocation: rank them
    # by their current load (variant 2b)
    def available_for(self, pickup_window: tuple[datetime, datetime]) -> list[DeliveryStaff]:
        return [
            driver
            for driver in self.users.list_delivery_staff()
            if any(slot.covers(pickup_window) for slot in self.slots_of(driver.user_id))
        ]
