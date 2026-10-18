# creates the accounts the web client acts as (cust-1, staff-1, ...). There's no login
# yet, so a caller must name an existing account. Safe to re-run
from swe.app import DeliveryManagementSystem, OnboardStaff, RegisterCustomer
from swe.repo import ConflictError

CUSTOMERS = [("cust-1", "Sam Customer"), ("cust-2", "Jo Customer")]
STAFF = [
    ("staff-1", "Alex Office", "office_staff"),
    ("owner-1", "Pat Owner", "business_owner"),
    ("driver-1", "Lee Driver", "delivery_staff"),
]


def main() -> None:
    dms = DeliveryManagementSystem()
    commands = [RegisterCustomer(user_id=i, name=n, phone="0400000000") for i, n in CUSTOMERS]
    commands += [OnboardStaff(user_id=i, name=n, phone="0400000000", role=r, by="seed") for i, n, r in STAFF]
    for command in commands:
        try:
            if isinstance(command, RegisterCustomer):
                dms.register_customer(command)
            else:
                dms.onboard_staff(command)
            print(f"created {command.user_id}")
        except ConflictError:
            print(f"exists  {command.user_id}")


if __name__ == "__main__":
    main()
