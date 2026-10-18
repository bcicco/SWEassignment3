from datetime import timedelta

import pytest

from swe.app import DeclareSlot, DeliveryManagementSystem, RemoveSlot
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import Customer, DeliveryStaff, StaffMember
from swe.repo import NotFoundError

T = now().replace(hour=9, minute=0, second=0, microsecond=0)


def at(hours: float):
    return T + timedelta(hours=hours)


@pytest.fixture
def dms(repo):
    dms = DeliveryManagementSystem(repo)
    for user in [
        DeliveryStaff(user_id="driver-1", name="Lee", phone="0400000001"),
        DeliveryStaff(user_id="driver-2", name="Kim", phone="0400000002"),
        StaffMember(user_id="staff-1", name="Alex", phone="0400000003"),
        Customer(user_id="cust-1", name="Sam", phone="0400000004"),
    ]:
        dms.users.add(user)
    return dms


def declare(dms, start, end, driver="driver-1"):
    return dms.declare_slot(DeclareSlot(delivery_staff_id=driver, window=(at(start), at(end)), by=driver))


def test_declared_slots_are_listed_in_start_order(dms):
    later = declare(dms, 6, 8)
    earlier = declare(dms, 0, 4)
    assert dms.roster.slots_of("driver-1") == [earlier, later]
    assert dms.roster.slots_of("driver-2") == []


def test_back_to_back_slots_are_allowed(dms):
    declare(dms, 0, 4)
    declare(dms, 4, 8)
    assert len(dms.roster.slots_of("driver-1")) == 2


def test_overlapping_slot_is_refused(dms):
    declare(dms, 0, 4)
    with pytest.raises(DomainError, match="overlaps"):
        declare(dms, 3, 6)
    assert len(dms.roster.slots_of("driver-1")) == 1
    declare(dms, 3, 6, driver="driver-2")  # another driver's slots don't clash


@pytest.mark.parametrize("user_id", ["staff-1", "cust-1"])
def test_only_drivers_declare_slots(dms, user_id):
    with pytest.raises(DomainError):
        declare(dms, 0, 4, driver=user_id)


def test_remove_slot(dms):
    slot = declare(dms, 0, 4)
    dms.remove_slot(RemoveSlot(delivery_staff_id="driver-1", slot_id=slot.id, by="driver-1"))
    assert dms.roster.slots_of("driver-1") == []
    declare(dms, 1, 3)  # the period can be declared again
    with pytest.raises(NotFoundError):
        dms.remove_slot(RemoveSlot(delivery_staff_id="driver-1", slot_id=slot.id, by="driver-1"))


def test_a_driver_cannot_remove_another_drivers_slot(dms):
    slot = declare(dms, 0, 4, driver="driver-2")
    with pytest.raises(NotFoundError):
        dms.remove_slot(RemoveSlot(delivery_staff_id="driver-1", slot_id=slot.id, by="driver-1"))
    assert dms.roster.slots_of("driver-2") == [slot]


def test_available_for_needs_a_slot_covering_the_whole_window(dms):
    declare(dms, 0, 4)  # driver-1: 9:00-13:00
    declare(dms, 2, 8, driver="driver-2")  # driver-2: 11:00-17:00
    names = lambda window: [d.user_id for d in dms.roster.available_for(window)]  # noqa: E731
    assert names((at(2), at(4))) == ["driver-1", "driver-2"]
    assert names((at(1), at(3))) == ["driver-1"]
    assert names((at(5), at(7))) == ["driver-2"]
    assert names((at(3), at(5))) == ["driver-2"]
    assert names((at(-1), at(1))) == []  # nobody covers the start


def test_drivers_with_no_slots_are_never_available(dms):
    assert dms.roster.available_for((at(0), at(1))) == []
