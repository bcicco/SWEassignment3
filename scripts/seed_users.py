# creates the accounts the web client acts as. There's no login, so a caller must name
# an existing account; account administration (Task 8) is out of scope. Safe to re-run
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
    users = DeliveryManagementSystem().users
    for user in USERS:
        try:
            users.add(user)
            print(f"created {user.user_id}")
        except ConflictError:
            print(f"exists  {user.user_id}")


if __name__ == "__main__":
    main()
