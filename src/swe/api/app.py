# Commands go through DeliveryManagementSystem, which enforces the business rules; reads
# go straight to the repository. Run with:
#   uv run uvicorn swe.api:create_app --factory --reload
from datetime import date, datetime

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from swe.api.identity import CurrentUser, Customer, Driver, Staff, is_customer, is_driver
from swe.api.models import (
    JobDetail,
    JobSummary,
    NewAdjustment,
    NewAllocation,
    NewPayment,
    NewQuote,
    NewReallocation,
    NewRequest,
    NewSlot,
    PaymentDetail,
    RequestDetail,
)
from swe.app import (
    AcceptQuote,
    AdjustPayment,
    AllocateJob,
    CancelRequest,
    Candidate,
    CloseJob,
    CollectionTotals,
    DeclareSlot,
    DeliveryManagementSystem,
    ForbiddenError,
    IssueQuote,
    LogRequest,
    ReallocateJob,
    RecordPayment,
    RejectQuote,
    RemoveSlot,
)
from swe.domain.job import Allocation, DeliveryJob, JobStateName, Payment, PaymentAdjustment
from swe.domain.request import DeliveryRequest, Quote, QuoteAccepted, RequestStatus
from swe.domain.user import AvailabilitySlot, DeliveryStaff
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


# pydantic's message lists every failed rule with the whole input; the user only needs
# the rules, e.g. "a reason is required when less than the amount due is collected"
def describe(exc: Exception) -> str:
    if not isinstance(exc, ValidationError):
        return str(exc)
    return "; ".join(
        ": ".join(filter(None, [".".join(map(str, e["loc"])), e["msg"].removeprefix("Value error, ")]))
        for e in exc.errors()
    )


def create_app(dms: DeliveryManagementSystem | None = None) -> FastAPI:
    dms = dms or DeliveryManagementSystem()
    repo = dms.repo
    app = FastAPI(title="YOWD Delivery Management System")
    app.state.dms = dms  # identity.current_user finds callers through it
    app.add_middleware(CORSMiddleware, allow_origins=CLIENT_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    for error, code in ERROR_STATUSES:

        def handle(request: Request, exc: Exception, code: int = code) -> JSONResponse:
            return JSONResponse(status_code=code, content={"detail": describe(exc)})

        app.add_exception_handler(error, handle)

    # a driver's own availability (Task 8)
    @app.get("/availability")
    def list_slots(user: Driver) -> list[AvailabilitySlot]:
        return dms.roster.slots_of(user.user_id)

    @app.post("/availability", status_code=status.HTTP_201_CREATED)
    def declare_slot(body: NewSlot, user: Driver) -> AvailabilitySlot:
        return dms.declare_slot(DeclareSlot(delivery_staff_id=user.user_id, window=body.window, by=user.user_id))

    @app.delete("/availability/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_slot(slot_id: str, user: Driver) -> None:
        dms.remove_slot(RemoveSlot(delivery_staff_id=user.user_id, slot_id=slot_id, by=user.user_id))

    # drivers free for a whole pickup window, for office staff allocating a job (Task 1)
    @app.get("/drivers/available")
    def available_drivers(start: datetime, end: datetime, user: Staff) -> list[DeliveryStaff]:
        return dms.roster.available_for((start, end))

    # customers see only their own requests; staff see all of them. Drivers work from
    # jobs, which carry the request's addresses and contact
    def visible_request(request_id: str, user: CurrentUser) -> DeliveryRequest:
        if is_driver(user):
            raise ForbiddenError("drivers see jobs, not requests")
        request = repo.get_request(request_id)
        if is_customer(user) and request.customer_id != user.user_id:
            raise ForbiddenError("not your request")
        return request

    @app.get("/requests")
    def list_requests(user: CurrentUser, status: RequestStatus | None = None) -> list[DeliveryRequest]:
        if is_driver(user):
            raise ForbiddenError("drivers see jobs, not requests")
        if is_customer(user):  # a customer has few requests, so filter them here
            return [r for r in repo.list_customer_requests(user.user_id) if status in (None, r.status)]
        statuses = [status] if status else list(RequestStatus)
        requests = [r for s in statuses for r in repo.list_requests_by_status(s)]
        return sorted(requests, key=lambda r: r.created_at, reverse=True)

    @app.post("/requests", status_code=status.HTTP_201_CREATED)
    def log_request(body: NewRequest, user: CurrentUser) -> DeliveryRequest:
        details = body.model_dump(exclude={"customer_id"})
        if is_customer(user):
            command = LogRequest(**details, customer_id=user.user_id)
        else:
            command = LogRequest(**details, customer_id=body.customer_id, logged_by=user.user_id)
        return dms.log_request(command)

    @app.get("/requests/{request_id}")
    def get_request(request_id: str, user: CurrentUser) -> RequestDetail:
        request = visible_request(request_id, user)
        quotes = sorted(repo.list_quotes(request_id), key=lambda q: q.time_of_issue, reverse=True)
        return RequestDetail(request=request, quotes=quotes, history=repo.get_history(request_id))

    @app.post("/requests/{request_id}/cancel")
    def cancel_request(request_id: str, user: CurrentUser) -> DeliveryRequest:
        visible_request(request_id, user)
        return dms.cancel_request(CancelRequest(request_id=request_id, by=user.user_id))

    @app.post("/requests/{request_id}/quotes", status_code=status.HTTP_201_CREATED)
    def issue_quote(request_id: str, body: NewQuote, user: Staff) -> Quote:
        return dms.issue_quote(IssueQuote(request_id=request_id, staff_id=user.user_id, **body.model_dump()))

    # the customer's responses; DeliveryManagementSystem checks it's their request
    # 202: the job (with the returned job_id) is created moments later by an event handler
    @app.post("/requests/{request_id}/quotes/{quote_id}/accept", status_code=status.HTTP_202_ACCEPTED)
    def accept_quote(request_id: str, quote_id: str, user: Customer) -> QuoteAccepted:
        return dms.accept_quote(AcceptQuote(request_id=request_id, quote_id=quote_id, customer_id=user.user_id))

    @app.post("/requests/{request_id}/quotes/{quote_id}/reject")
    def reject_quote(request_id: str, quote_id: str, user: Customer) -> Quote:
        return dms.reject_quote(RejectQuote(request_id=request_id, quote_id=quote_id, customer_id=user.user_id))

    # customers see only their own jobs and drivers only the ones allocated to them
    # (QA3.2); staff see all of them
    def visible_job(job_id: str, user: CurrentUser) -> DeliveryJob:
        job = repo.get_job(job_id)
        if is_customer(user) and job.customer_id != user.user_id:
            raise ForbiddenError("not your job")
        if is_driver(user) and job.delivery_staff_id != user.user_id:
            raise ForbiddenError("not allocated to you")
        return job

    @app.get("/jobs")
    def list_jobs(user: CurrentUser, state: JobStateName | None = None) -> list[JobSummary]:
        if is_customer(user):
            jobs = [j for j in repo.list_customer_jobs(user.user_id) if state in (None, j.state)]
        elif is_driver(user):
            jobs = [j for j in repo.list_driver_jobs(user.user_id) if state in (None, j.state)]
        else:
            states = [state] if state else list(JobStateName)
            jobs = sorted(
                (j for s in states for j in repo.list_jobs_by_state(s)), key=lambda j: j.created_at, reverse=True
            )
        # one read per job for its route and contact; fine at this scale
        return [JobSummary(job=j, request=repo.get_request(j.request_id)) for j in jobs]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, user: CurrentUser) -> JobDetail:
        job = visible_job(job_id, user)
        return JobDetail(
            job=job,
            request=repo.get_request(job.request_id),
            quote=repo.get_quote(job.request_id, job.quote_id),
            allocations=repo.list_allocations(job_id),
        )

    # Task 1: office staff find a driver for the job's pickup window and allocate it
    @app.get("/jobs/{job_id}/candidates")
    def job_candidates(job_id: str, user: Staff) -> list[Candidate]:
        return dms.job_candidates(job_id)

    @app.post("/jobs/{job_id}/allocate", status_code=status.HTTP_201_CREATED)
    def allocate_job(job_id: str, body: NewAllocation, user: Staff) -> Allocation:
        return dms.allocate_job(AllocateJob(job_id=job_id, delivery_staff_id=body.delivery_staff_id, by=user.user_id))

    @app.post("/jobs/{job_id}/reallocate", status_code=status.HTTP_201_CREATED)
    def reallocate_job(job_id: str, body: NewReallocation, user: Staff) -> Allocation:
        command = ReallocateJob(job_id=job_id, **body.model_dump(), by=user.user_id)
        return dms.reallocate_job(command)

    # Task 7: what the job owes and every payment and adjustment towards it
    @app.get("/jobs/{job_id}/payments")
    def job_payments(job_id: str, user: CurrentUser) -> PaymentDetail:
        job = visible_job(job_id, user)
        return PaymentDetail(
            settlement=dms.settlement(job),
            payments=repo.list_payments(job_id),
            adjustments=repo.list_adjustments(job_id),
        )

    # the allocated driver at collection; the façade checks it's their job
    @app.post("/jobs/{job_id}/payments", status_code=status.HTTP_201_CREATED)
    def record_payment(job_id: str, body: NewPayment, user: Driver) -> Payment:
        return dms.record_payment(RecordPayment(job_id=job_id, **body.model_dump(), by=user.user_id))

    @app.post("/jobs/{job_id}/payments/{payment_id}/adjustments", status_code=status.HTTP_201_CREATED)
    def adjust_payment(job_id: str, payment_id: str, body: NewAdjustment, user: Staff) -> PaymentAdjustment:
        command = AdjustPayment(job_id=job_id, payment_id=payment_id, **body.model_dump(), by=user.user_id)
        return dms.adjust_payment(command)

    @app.post("/jobs/{job_id}/close")
    def close_job(job_id: str, user: Staff) -> DeliveryJob:
        return dms.close_job(CloseJob(job_id=job_id, by=user.user_id))

    # Task 7 variant 5a: office staff see anyone's daily totals, drivers only their own
    @app.get("/collections")
    def collections(user: CurrentUser, day: date, staff_id: str | None = None) -> CollectionTotals:
        if is_customer(user):
            raise ForbiddenError("only staff can see collection totals")
        staff_id = staff_id or user.user_id
        if is_driver(user) and staff_id != user.user_id:
            raise ForbiddenError("drivers can only see their own collections")
        return dms.collection_totals(staff_id, day)

    return app
