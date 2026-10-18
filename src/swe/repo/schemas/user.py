from swe.domain.user import Customer, DeliveryStaff, StaffMember, User
from swe.repo.schema import Index, ItemSchema, String, Timestamp

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
