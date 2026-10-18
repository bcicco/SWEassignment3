from swe.domain.user import DeliveryStaff, User
from swe.repo import Repository


# Accounts (§4.2): finding the one behind a caller's identity. Accounts are seeded
# (scripts/seed_users.py); creating, onboarding and deactivating them (Task 8) is
# out of scope. Rostering questions belong to StaffRoster, not here
class UserDirectory:
    def __init__(self, repo: Repository):
        self.repo = repo

    # ConflictError if the id already has an account
    def add(self, user: User) -> None:
        self.repo.transaction().create(user).commit()

    # NotFoundError if there's no account
    def find(self, user_id: str) -> User:
        return self.repo.get_user(user_id)

    # every driver, for StaffRoster to match against a job's pickup window. Read from
    # an index, so a just-added driver may take a moment to appear
    def list_delivery_staff(self) -> list[DeliveryStaff]:
        return sorted(self.repo.list_delivery_staff(), key=lambda d: d.user_id)
