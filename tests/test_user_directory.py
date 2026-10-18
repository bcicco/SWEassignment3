import pytest

from swe.app import DeactivateUser, DeliveryManagementSystem, ForbiddenError, OnboardStaff, RegisterCustomer
from swe.domain.shared import DomainError
from swe.domain.user import Customer, DeliveryStaff, StaffMember, StaffRole
from swe.repo import ConflictError, NotFoundError


@pytest.fixture
def dms(repo):
    return DeliveryManagementSystem(repo)


def register(dms, user_id="cust-1"):
    return dms.register_customer(RegisterCustomer(user_id=user_id, name="Sam", phone="0400000000"))


def onboard(dms, user_id, role):
    return dms.onboard_staff(OnboardStaff(user_id=user_id, name="Alex", phone="0411111111", role=role, by="owner-1"))


def test_register_and_find(dms):
    register(dms)
    found = dms.users.find("cust-1")
    assert isinstance(found, Customer)
    assert (found.name, found.is_active) == ("Sam", True)


def test_an_id_has_one_account(dms):
    register(dms)
    with pytest.raises(ConflictError):
        register(dms)
    with pytest.raises(ConflictError):
        onboard(dms, "cust-1", "office_staff")


@pytest.mark.parametrize(
    ("role", "kind", "staff_role"),
    [
        ("office_staff", StaffMember, StaffRole.OFFICE_STAFF),
        ("business_owner", StaffMember, StaffRole.BUSINESS_OWNER),
        ("delivery_staff", DeliveryStaff, None),
    ],
)
def test_onboarded_staff_load_as_their_kind(dms, role, kind, staff_role):
    onboard(dms, "staff-1", role)
    found = dms.users.find("staff-1")
    assert type(found) is kind
    assert getattr(found, "role", None) == staff_role


def test_deactivation_keeps_the_account(dms):
    register(dms)
    dms.deactivate_user(DeactivateUser(user_id="cust-1", by="owner-1"))
    found = dms.users.find("cust-1")
    assert not found.is_active  # still there for past records (PR8)
    with pytest.raises(ForbiddenError):
        dms.identify("cust-1")


def test_deactivating_twice_is_refused(dms):
    register(dms)
    dms.deactivate_user(DeactivateUser(user_id="cust-1", by="owner-1"))
    with pytest.raises(DomainError):
        dms.deactivate_user(DeactivateUser(user_id="cust-1", by="owner-1"))


def test_concurrent_deactivation_conflicts(dms):
    register(dms)
    loaded = dms.users.find("cust-1")
    dms.deactivate_user(DeactivateUser(user_id="cust-1", by="owner-1"))
    loaded.deactivate()
    with pytest.raises(ConflictError):
        dms.repo.transaction().update(loaded, ["deactivated_at"], where={"deactivated_at": None}).commit()


def test_unknown_user(dms):
    with pytest.raises(NotFoundError):
        dms.identify("nobody")
