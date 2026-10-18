from swe.domain.user import User
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
