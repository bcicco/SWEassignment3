import pytest

from swe.app import DeliveryManagementSystem
from swe.domain.user import Customer, DeliveryStaff, StaffMember
from swe.repo import ConflictError, NotFoundError


@pytest.fixture
def dms(repo):
    return DeliveryManagementSystem(repo)


@pytest.mark.parametrize("kind", [Customer, StaffMember, DeliveryStaff])
def test_accounts_load_as_their_kind(dms, kind):
    dms.users.add(kind(user_id="u-1", name="Sam", phone="0400000000"))
    found = dms.identify("u-1")
    assert type(found) is kind
    assert found.name == "Sam"


def test_an_id_has_one_account(dms):
    dms.users.add(Customer(user_id="u-1", name="Sam", phone="0400000000"))
    with pytest.raises(ConflictError):
        dms.users.add(StaffMember(user_id="u-1", name="Alex", phone="0411111111"))


def test_unknown_user(dms):
    with pytest.raises(NotFoundError):
        dms.identify("nobody")


def test_list_delivery_staff_returns_only_drivers(dms):
    for user in [
        DeliveryStaff(user_id="driver-2", name="Kim", phone="0400000002"),
        Customer(user_id="cust-1", name="Sam", phone="0400000000"),
        StaffMember(user_id="staff-1", name="Alex", phone="0411111111"),
        DeliveryStaff(user_id="driver-1", name="Lee", phone="0400000001"),
    ]:
        dms.users.add(user)
    drivers = dms.users.list_delivery_staff()
    assert [d.user_id for d in drivers] == ["driver-1", "driver-2"]
    assert all(type(d) is DeliveryStaff for d in drivers)


def test_no_drivers(dms):
    assert dms.users.list_delivery_staff() == []
