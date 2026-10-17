from enum import Enum

from pydantic import computed_field

from shared.base import Record


class EventType(str, Enum):
    REQUEST_LOGGED = "request_logged"
    REQUEST_CANCELLED = "request_cancelled"
    QUOTE_ISSUED = "quote_issued"
    QUOTE_SUPERSEDED = "quote_superseded"
    QUOTE_ACCEPTED = "quote_accepted"
    QUOTE_REJECTED = "quote_rejected"
    QUOTE_REVISION_REQUESTED = "quote_revision_requested"


# one immutable entry in a request's history; the job appends to the same trail
class HistoryEvent(Record):
    request_id: str
    event_type: EventType
    reference_id: str | None = None # the quote or job the event is about

    @computed_field
    @property
    def pk(self) -> str:
        return f"REQUEST#{self.request_id}"

    # timestamp first so events sort chronologically
    @computed_field
    @property
    def sk(self) -> str:
        return f"EVENT#{self.created_at.isoformat()}#{self.id}"
