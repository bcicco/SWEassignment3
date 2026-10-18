# Each handler is a Lambda targeted by its EventBridge rule. It declares the events
# it accepts with @handles and receives them typed.
# Delivery is at-least-once, so handlers must be idempotent (dedupe on event.id).
import logging

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


@handles(RequestLogged, QuoteAccepted, QuoteRejected)
def notify_office_staff(event: RequestLogged | QuoteAccepted | QuoteRejected) -> None:
    match event:
        case RequestLogged():
            log.info("NOTIFY office staff: request %s needs a quote", event.request_id)
        case QuoteAccepted():
            log.info("NOTIFY office staff: job %s needs allocation (quote %s)", event.job_id, event.quote_id)
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


@handles()
def audit(event: HistoryEvent) -> None:
    log.info("AUDIT: %s by %s at %s", event.event_type, event.created_by, event.created_at)
