# who is calling. There's no login yet: the client says who it is acting as in two
# headers, and this is the only place that reads them, so authentication can replace
# it without changing any endpoint
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Header
from pydantic import BaseModel

from swe.app import ForbiddenError


class Role(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"


class User(BaseModel):
    id: str
    role: Role


def current_user(
    x_user_id: Annotated[str, Header(min_length=1)],
    x_user_role: Annotated[Role, Header()],
) -> User:
    return User(id=x_user_id, role=x_user_role)


def _require(role: Role):
    def check(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role is not role:
            raise ForbiddenError(f"only {role.value} can do this")
        return user

    return check


CurrentUser = Annotated[User, Depends(current_user)]
Customer = Annotated[User, Depends(_require(Role.CUSTOMER))]
Staff = Annotated[User, Depends(_require(Role.STAFF))]
