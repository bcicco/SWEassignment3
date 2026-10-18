# who is calling. There's no login yet: the client names the account it acts as in the
# X-User-Id header, standing in for the platform's authentication (A11). This is the
# only place that reads it. Whether the caller is a customer, office staff or a driver
# comes from their account in the UserDirectory,
# never from the client
from typing import Annotated

from fastapi import Depends, Header, Request

from swe.app import ForbiddenError
from swe.domain.user import Customer as CustomerAccount
from swe.domain.user import StaffMember, User
from swe.repo import NotFoundError


def current_user(request: Request, x_user_id: Annotated[str, Header(min_length=1)]) -> User:
    try:
        return request.app.state.dms.identify(x_user_id)
    except NotFoundError:
        raise ForbiddenError("no account for this user") from None


def _require(allowed, description: str):
    def check(user: Annotated[User, Depends(current_user)]) -> User:
        if not allowed(user):
            raise ForbiddenError(f"only {description} can do this")
        return user

    return check


def is_customer(user: User) -> bool:
    return isinstance(user, CustomerAccount)


CurrentUser = Annotated[User, Depends(current_user)]
Customer = Annotated[CustomerAccount, Depends(_require(is_customer, "customers"))]
Staff = Annotated[StaffMember, Depends(_require(lambda u: isinstance(u, StaffMember), "office staff"))]
