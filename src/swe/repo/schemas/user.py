from swe.domain.user import Customer, DeliveryStaff, StaffMember, StaffRole, User
from swe.repo.schema import Enum, ItemSchema, Optional, String, Timestamp

USER = ItemSchema(
    User,
    pk="USER#{user_id}",
    sk="METADATA",
    attributes={
        "user_id": String,
        "name": String,
        "phone": String,
        "created_at": Timestamp,
        "deactivated_at": Optional(Timestamp),
    },
)

CUSTOMER = USER.extend(Customer, {"kind": String})
STAFF_MEMBER = USER.extend(StaffMember, {"kind": String, "role": Enum(StaffRole)})
DELIVERY_STAFF = USER.extend(DeliveryStaff, {"kind": String})
