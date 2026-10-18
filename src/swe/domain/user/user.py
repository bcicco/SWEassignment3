from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.shared.errors import DomainError
from swe.domain.shared.ids import now


# the shared identity and account status of every account (§4.3). The id is the one
# the platform's authentication supplies (A11). Accounts are never deleted, so past
# records still resolve to a person after deactivation (PR8)
class User(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    user_id: str = Field(min_length=1, frozen=True)
    name: str = Field(min_length=1, frozen=True)
    phone: str = Field(min_length=1, frozen=True)
    created_at: datetime = Field(default_factory=now, frozen=True)
    deactivated_at: datetime | None = None  # only ever set once, so the repo locks on it

    @property
    def is_active(self) -> bool:
        return self.deactivated_at is None

    def deactivate(self, at: datetime | None = None) -> None:
        if not self.is_active:
            raise DomainError("account is already deactivated")
        self.deactivated_at = at or now()


class Customer(User):
    kind: Literal["customer"] = "customer"


# office staff and business owners differ only in permissions, so they're roles (A10, §1.4.4)
class StaffRole(StrEnum):
    OFFICE_STAFF = "office_staff"
    BUSINESS_OWNER = "business_owner"


class StaffMember(User):
    kind: Literal["staff_member"] = "staff_member"
    role: StaffRole = Field(frozen=True)

    @property
    def is_business_owner(self) -> bool:
        return self.role is StaffRole.BUSINESS_OWNER


# a sibling of StaffMember, so no office-only responsibility reaches a driver (§3.3)
class DeliveryStaff(User):
    kind: Literal["delivery_staff"] = "delivery_staff"


# any stored account, told apart by kind
AnyUser = Annotated[Customer | StaffMember | DeliveryStaff, Field(discriminator="kind")]
