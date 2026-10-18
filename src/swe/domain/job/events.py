# events raised by DeliveryJob (§4.5). They go in the job's request's history
from typing import Literal

from swe.domain.shared.history_event import HistoryEvent


class JobCreated(HistoryEvent):
    event_type: Literal["job_created"] = "job_created"
    job_id: str
