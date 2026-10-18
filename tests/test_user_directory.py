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
