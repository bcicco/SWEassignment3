# Each handler is a Lambda targeted by its EventBridge rule. It declares the events
# it accepts with @handles and receives them typed.
# Delivery is at-least-once, so handlers must be idempotent (dedupe on event.id).
import logging
from functools import cache

from swe.app import CreateDeliveryJob, DeliveryManagementSystem
from swe.domain.job import JobAllocated, JobCreated
from swe.domain.request import (
    QuoteAccepted,
    QuoteIssued,
    QuoteRejected,
    RequestCancelled,
    RequestLogged,
)
from swe.domain.shared import HistoryEvent
from swe.events.handling import handles

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)  # the Lambda runtime defaults to WARNING


# one per Lambda container, reused across invocations
@cache
def system() -> DeliveryManagementSystem:
    return DeliveryManagementSystem()


# accepting a quote doesn't create the job; this does, so requests never write jobs.
# Raising makes EventBridge retry, and a redelivered event finds the job already there
@handles(QuoteAccepted)
def create_delivery_job(event: QuoteAccepted) -> None:
    command = CreateDeliveryJob(
        job_id=event.job_id, request_id=event.request_id, quote_id=event.quote_id, customer_id=event.customer_id
    )
    job = system().create_delivery_job(command)
    log.info("CREATED job %s for request %s", job.job_id, job.request_id)


@handles(RequestLogged, JobCreated, QuoteRejected)
def notify_office_staff(event: RequestLogged | JobCreated | QuoteRejected) -> None:
    match event:
        case RequestLogged():
            log.info("NOTIFY office staff: request %s needs a quote", event.request_id)
        case JobCreated():
            log.info("NOTIFY office staff: job %s needs allocation (request %s)", event.job_id, event.request_id)
        case QuoteRejected():
            log.info("NOTIFY office staff: quote %s was rejected", event.quote_id)


@handles(QuoteIssued, RequestCancelled)
def notify_customer(event: QuoteIssued | RequestCancelled) -> None:
    match event:
        case QuoteIssued():
            log.info(
                "NOTIFY customer: quote %s for $%s, valid until %s", event.quote_id, event.price, event.expiry_time
            )
        case RequestCancelled():
            log.info("NOTIFY customer: request %s cancelled", event.request_id)


# the new driver gets the job; on a reallocation the previous one is told it's gone
@handles(JobAllocated)
def notify_driver(event: JobAllocated) -> None:
    log.info("NOTIFY driver %s: job %s allocated to you", event.delivery_staff_id, event.job_id)
    if event.previous_delivery_staff_id:
        log.info(
            "NOTIFY driver %s: job %s reallocated (%s)", event.previous_delivery_staff_id, event.job_id, event.reason
        )


@handles()
def audit(event: HistoryEvent) -> None:
    log.info("AUDIT: %s by %s at %s", event.event_type, event.created_by, event.created_at)
