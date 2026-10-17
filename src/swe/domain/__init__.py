# importing each domain registers its events with HistoryEvent, so
# parse_history_event can build any of them
from swe.domain import job, request  # noqa: F401
