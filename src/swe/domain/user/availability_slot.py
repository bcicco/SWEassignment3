from datetime import datetime

from pydantic import field_validator

from swe.domain.shared.base import Record


# A period a driver says they can work (§4.9). Never edited: a change is a removal
# and a new declaration (§3.3). created_by is whoever declared it
class AvailabilitySlot(Record):
    delivery_staff_id: str
    window: tuple[datetime, datetime]

    @field_validator("window")
    @classmethod
    def _window_in_order(cls, window: tuple[datetime, datetime]) -> tuple[datetime, datetime]:
        if window[1] <= window[0]:
            raise ValueError("window must end after it starts")
        return window

    # the driver is free for the whole pickup window, not just part of it
    def covers(self, pickup_window: tuple[datetime, datetime]) -> bool:
        start, end = self.window
        return start <= pickup_window[0] and pickup_window[1] <= end

    # slots that only touch (one ends as the next starts) don't overlap, so a day can
    # be split into back-to-back slots (Task 8 1a)
    def overlaps(self, other: "AvailabilitySlot") -> bool:
        return self.window[0] < other.window[1] and other.window[0] < self.window[1]
