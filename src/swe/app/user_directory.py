from collections.abc import Callable
from datetime import datetime

from swe.app.commands import DeactivateUser, OnboardStaff, RegisterCustomer
from swe.app.errors import ForbiddenError
from swe.domain.shared.ids import now
from swe.domain.user import Customer, DeliveryStaff, StaffMember, StaffRole, User
from swe.repo import Repository


# Accounts: creating and onboarding them, finding the one behind a caller's identity,
# and deactivating them (§4.2). Rostering questions belong to StaffRoster, not here.
#
# TODO once they exist: record every change here to AuditLog (QA3.10), and tell
# StaffRoster when a DeliveryStaff is onboarded or deactivated
class UserDirectory:
    def __init__(self, repo: Repository, clock: Callable[[], datetime] = now):
        self.repo = repo
        self.clock = clock

    # ConflictError if the id already has an account
    def register_customer(self, command: RegisterCustomer) -> Customer:
        customer = Customer(**command.model_dump(), created_at=self.clock())
        self.repo.transaction().create(customer).commit()
        return customer

    def onboard_staff(self, command: OnboardStaff) -> StaffMember | DeliveryStaff:
        details = dict(user_id=command.user_id, name=command.name, phone=command.phone, created_at=self.clock())
        if command.role == "delivery_staff":
            user = DeliveryStaff(**details)
        else:
            user = StaffMember(**details, role=StaffRole(command.role))
        self.repo.transaction().create(user).commit()
        return user

    def find(self, user_id: str) -> User:
        return self.repo.get_user(user_id)

    # a deactivated account can do nothing from the moment it's deactivated (QA3.9)
    def find_active(self, user_id: str) -> User:
        user = self.find(user_id)
        if not user.is_active:
            raise ForbiddenError("this account has been deactivated")
        return user

    # TODO: for DeliveryStaff, Dispatcher must first confirm no active jobs are
    # allocated to them (Task 1 5a; QA3.9). Nothing can be allocated yet
    def deactivate(self, command: DeactivateUser) -> User:
        user = self.find(command.user_id)
        user.deactivate(self.clock())
        self.repo.transaction().update(user, ["deactivated_at"], where={"deactivated_at": None}).commit()
        return user
