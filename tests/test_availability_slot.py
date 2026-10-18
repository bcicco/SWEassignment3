from datetime import timedelta

import pytest
from pydantic import ValidationError

from swe.domain.shared.ids import now
from swe.domain.user import AvailabilitySlot

T = now().replace(hour=9, minute=0, second=0, microsecond=0)


def at(hours: float):
    return T + timedelta(hours=hours)


def slot(start: float, end: float) -> AvailabilitySlot:
    return AvailabilitySlot(delivery_staff_id="driver-1", window=(at(start), at(end)), created_by="driver-1")


@pytest.mark.parametrize(
    ("pickup", "covered"),
    [
        ((1, 2), True),  # inside
        ((0, 4), True),  # exactly the slot
        ((-1, 1), False),  # starts before the slot
        ((3, 5), False),  # runs past the end
        ((5, 6), False),  # after it entirely
    ],
)
def test_covers_only_whole_pickup_windows(pickup, covered):
    assert slot(0, 4).covers((at(pickup[0]), at(pickup[1]))) is covered


@pytest.mark.parametrize(
    ("other", "overlapping"),
    [
        ((2, 6), True),  # partly
        ((1, 2), True),  # inside
        ((-1, 5), True),  # around
        ((4, 6), False),  # back to back after
        ((-2, 0), False),  # back to back before
        ((5, 6), False),  # apart
    ],
)
def test_overlaps(other, overlapping):
    first, second = slot(0, 4), slot(*other)
    assert first.overlaps(second) is overlapping
    assert second.overlaps(first) is overlapping  # either way round


def test_window_must_end_after_it_starts():
    with pytest.raises(ValidationError):
        slot(2, 2)
    with pytest.raises(ValidationError):
        slot(3, 1)


def test_slots_are_never_edited():
    s = slot(0, 4)
    with pytest.raises(ValidationError):
        s.window = (at(1), at(5))
