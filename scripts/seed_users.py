# creates the accounts the web client acts as. There's no login, so a caller must name
# an existing account; account administration (Task 8) is out of scope. Safe to re-run:
# an existing account is saved again, so it picks up any index added since
from swe.app import DeliveryManagementSystem
from swe.domain.user import Customer, DeliveryStaff, StaffMember
from swe.repo import ConflictError

USERS = [
    Customer(user_id="cust-1", name="Sam Customer", phone="0400000001"),
    Customer(user_id="cust-2", name="Jo Customer", phone="0400000002"),
    StaffMember(user_id="staff-1", name="Alex Office", phone="0400000003"),
    DeliveryStaff(user_id="driver-1", name="Lee Driver", phone="0400000004"),
]


def main() -> None:
    dms = DeliveryManagementSystem()
    for user in USERS:
        try:
            dms.repo.transaction().delete(user).commit()
            print(f"resaved {user.user_id}")
        except ConflictError:  # not there yet
            print(f"created {user.user_id}")
        dms.users.add(user)


if __name__ == "__main__":
    main()
