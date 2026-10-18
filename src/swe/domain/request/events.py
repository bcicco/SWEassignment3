# events raised by DeliveryRequest and Quote (§4.4)
from datetime import datetime
from decimal import Decimal
from typing import Literal

from swe.domain.shared.history_event import HistoryEvent


class RequestLogged(HistoryEvent):
    event_type: Literal["request_logged"] = "request_logged"
    customer_id: str | None = None  # None for anonymous requests (A9)
    logged_by: str | None = None  # office staff logging for a caller (Task 5)


class RequestCancelled(HistoryEvent):
    event_type: Literal["request_cancelled"] = "request_cancelled"


class QuoteIssued(HistoryEvent):
    event_type: Literal["quote_issued"] = "quote_issued"
    quote_id: str
    price: Decimal
    expiry_time: datetime
    supersedes: str | None = None  # the quote this one replaced, if any (A6)


# the job is created from this by the create-delivery-job handler; its id is chosen
# here so redelivering the event can't create a second job
class QuoteAccepted(HistoryEvent):
    event_type: Literal["quote_accepted"] = "quote_accepted"
    quote_id: str
    job_id: str
    customer_id: str  # who will own the job


class QuoteRejected(HistoryEvent):
    event_type: Literal["quote_rejected"] = "quote_rejected"
    quote_id: str
