from swe.domain.user import AvailabilitySlot, Customer, DeliveryStaff, StaffMember, User
from swe.repo.schema import Index, ItemSchema, Optional, String, Timestamp, Window

# the accounts of each kind, e.g. every driver for StaffRoster
USERS_BY_KIND = Index("users_by_kind", pk="USER_KIND#{kind}", sk="USER#{user_id}")

USER = ItemSchema(
    User,
    pk="USER#{user_id}",
    sk="METADATA",
    attributes={
        "user_id": String,
        "name": String,
        "phone": String,
        "created_at": Timestamp,
    },
)

CUSTOMER = USER.extend(Customer, {"kind": String}, indexes=(USERS_BY_KIND,))
STAFF_MEMBER = USER.extend(StaffMember, {"kind": String}, indexes=(USERS_BY_KIND,))
DELIVERY_STAFF = USER.extend(DeliveryStaff, {"kind": String}, indexes=(USERS_BY_KIND,))

# a driver's slots live in their partition, in start order (A2 Figure 2: DeliveryStaff
# composes its AvailabilitySlots)
AVAILABILITY_SLOT = ItemSchema(
    AvailabilitySlot,
    pk="USER#{delivery_staff_id}",
    sk="SLOT#{window[0]}#{id}",
    attributes={
        "id": String,
        "created_at": Timestamp,
        "created_by": Optional(String),
        "delivery_staff_id": String,
        "window": Window,
    },
)
