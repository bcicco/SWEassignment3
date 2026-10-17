# Commands go through DeliveryManagementSystem, which enforces the business rules; reads
# go straight to the repository. Run with:
#   uv run uvicorn swe.api:create_app --factory --reload
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from swe.api.identity import CurrentUser, Customer, Role, Staff
from swe.api.models import NewQuote, NewRequest, RequestDetail
from swe.app import (
    AcceptQuote,
    CancelRequest,
    DeliveryManagementSystem,
    ForbiddenError,
    IssueQuote,
    LogRequest,
    RejectQuote,
    RequestQuoteRevision,
)
from swe.domain.job import DeliveryJob
from swe.domain.request import DeliveryRequest, Quote, RequestStatus
from swe.repo import ConflictError, NotFoundError

# the React dev server (Vite's default port)
CLIENT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# most specific first: DomainError and pydantic's ValidationError are both ValueErrors
ERROR_STATUSES = [
    (ForbiddenError, status.HTTP_403_FORBIDDEN),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),  # changed since loaded; the client should reload
    (ValueError, status.HTTP_400_BAD_REQUEST),  # a business rule refused it
]


def create_app(dms: DeliveryManagementSystem | None = None) -> FastAPI:
    dms = dms or DeliveryManagementSystem()
    repo = dms.repo
    app = FastAPI(title="YOWD Delivery Management System")
    app.add_middleware(CORSMiddleware, allow_origins=CLIENT_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    for error, code in ERROR_STATUSES:

        def handle(request: Request, exc: Exception, code: int = code) -> JSONResponse:
            return JSONResponse(status_code=code, content={"detail": str(exc)})

        app.add_exception_handler(error, handle)

    # customers see only their own requests; staff see all of them
    def visible_request(request_id: str, user: CurrentUser) -> DeliveryRequest:
        request = repo.get_request(request_id)
        if user.role is Role.CUSTOMER and request.customer_id != user.id:
            raise ForbiddenError("not your request")
        return request

    @app.get("/requests")
    def list_requests(user: CurrentUser, status: RequestStatus | None = None) -> list[DeliveryRequest]:
        if user.role is Role.CUSTOMER:  # a customer has few requests, so filter them here
            return [r for r in repo.list_customer_requests(user.id) if status in (None, r.status)]
        statuses = [status] if status else list(RequestStatus)
        requests = [r for s in statuses for r in repo.list_requests_by_status(s)]
        return sorted(requests, key=lambda r: r.created_at, reverse=True)

    @app.post("/requests", status_code=status.HTTP_201_CREATED)
    def log_request(body: NewRequest, user: CurrentUser) -> DeliveryRequest:
        details = body.model_dump(exclude={"customer_id"})
        if user.role is Role.CUSTOMER:
            command = LogRequest(**details, customer_id=user.id)
        else:
            command = LogRequest(**details, customer_id=body.customer_id, logged_by=user.id)
        return dms.log_request(command)

    @app.get("/requests/{request_id}")
    def get_request(request_id: str, user: CurrentUser) -> RequestDetail:
        request = visible_request(request_id, user)
        quotes = sorted(repo.list_quotes(request_id), key=lambda q: q.time_of_issue, reverse=True)
        return RequestDetail(request=request, quotes=quotes, history=repo.get_history(request_id))

    @app.post("/requests/{request_id}/cancel")
    def cancel_request(request_id: str, user: CurrentUser) -> DeliveryRequest:
        visible_request(request_id, user)
        return dms.cancel_request(CancelRequest(request_id=request_id, by=user.id))

    @app.post("/requests/{request_id}/quotes", status_code=status.HTTP_201_CREATED)
    def issue_quote(request_id: str, body: NewQuote, user: Staff) -> Quote:
        return dms.issue_quote(IssueQuote(request_id=request_id, staff_id=user.id, **body.model_dump()))

    # the customer's responses; DeliveryManagementSystem checks it's their request
    @app.post("/requests/{request_id}/quotes/{quote_id}/accept", status_code=status.HTTP_201_CREATED)
    def accept_quote(request_id: str, quote_id: str, user: Customer) -> DeliveryJob:
        return dms.accept_quote(AcceptQuote(request_id=request_id, quote_id=quote_id, customer_id=user.id))

    @app.post("/requests/{request_id}/quotes/{quote_id}/reject")
    def reject_quote(request_id: str, quote_id: str, user: Customer) -> Quote:
        return dms.reject_quote(RejectQuote(request_id=request_id, quote_id=quote_id, customer_id=user.id))

    @app.post("/requests/{request_id}/quotes/{quote_id}/revision")
    def request_quote_revision(request_id: str, quote_id: str, user: Customer) -> Quote:
        command = RequestQuoteRevision(request_id=request_id, quote_id=quote_id, customer_id=user.id)
        return dms.request_quote_revision(command)

    return app
