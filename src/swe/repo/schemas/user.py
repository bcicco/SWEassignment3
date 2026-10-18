from swe.domain.user import Customer, DeliveryStaff, StaffMember, User
from swe.repo.schema import ItemSchema, String, Timestamp

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

CUSTOMER = USER.extend(Customer, {"kind": String})
STAFF_MEMBER = USER.extend(StaffMember, {"kind": String})
DELIVERY_STAFF = USER.extend(DeliveryStaff, {"kind": String})
