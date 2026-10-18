# who is calling. There's no login yet: the client names the account it acts as in the
# X-User-Id header, standing in for the platform's authentication (A11). This is the
# only place that reads it. The account's kind and role come from the UserDirectory,
# never from the client
from typing import Annotated

from fastapi import Depends, Header, Request

from swe.app import ForbiddenError
from swe.domain.user import Customer as CustomerAccount
from swe.domain.user import StaffMember, User
from swe.repo import NotFoundError


# the authenticated identity, whether or not it has an account yet (for registering)
def caller_id(x_user_id: Annotated[str, Header(min_length=1)]) -> str:
    return x_user_id


def current_user(request: Request, user_id: Annotated[str, Depends(caller_id)]) -> User:
    try:
        return request.app.state.dms.identify(user_id)
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


CallerId = Annotated[str, Depends(caller_id)]
CurrentUser = Annotated[User, Depends(current_user)]
Customer = Annotated[CustomerAccount, Depends(_require(is_customer, "customers"))]
# office staff, or a business owner covering the office
Staff = Annotated[StaffMember, Depends(_require(lambda u: isinstance(u, StaffMember), "office staff"))]
BusinessOwner = Annotated[
    StaffMember,
    Depends(_require(lambda u: isinstance(u, StaffMember) and u.is_business_owner, "business owners")),
]
