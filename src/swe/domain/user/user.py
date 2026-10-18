from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.shared.ids import now


# the shared identity of every account (§4.3). The id is the one the platform's
# authentication supplies (A11). Accounts are seeded; administering them (Task 8)
# is out of scope
class User(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=now)


class Customer(User):
    kind: Literal["customer"] = "customer"


# office staff. The design's separate Business Owner role (A10) was dropped, as
# nothing behaves differently for it
class StaffMember(User):
    kind: Literal["staff_member"] = "staff_member"


# a sibling of StaffMember, so no office-only responsibility reaches a driver (§3.3)
class DeliveryStaff(User):
    kind: Literal["delivery_staff"] = "delivery_staff"
