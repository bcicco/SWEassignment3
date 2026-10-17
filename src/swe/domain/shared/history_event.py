from typing import ClassVar

from pydantic import computed_field

from swe.domain.shared.base import Record


# one immutable entry in a request's history (§1.4.2). Each domain defines its own
# subclasses next to the models that raise them; a subclass is both the stored record
# and the payload (EventBridge `detail`) emitted for it.
#
# Subclasses register themselves by their event_type, so adding an event is just
# defining the class: e.g. `event_type: Literal["quote_issued"] = "quote_issued"`
class HistoryEvent(Record):
    registry: ClassVar[dict[str, type["HistoryEvent"]]] = {}
    TYPE: ClassVar[str]
    request_id: str

    # runs once pydantic has built the subclass's fields
    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        event_type = cls.model_fields["event_type"].default
        if event_type in HistoryEvent.registry:
            raise TypeError(f"event_type {event_type!r} is already used by {HistoryEvent.registry[event_type].__name__}")
        cls.TYPE = event_type
        HistoryEvent.registry[event_type] = cls

    @computed_field
    @property
    def pk(self) -> str:
        return f"REQUEST#{self.request_id}"

    # timestamp first so events sort chronologically
    @computed_field
    @property
    def sk(self) -> str:
        return f"EVENT#{self.created_at.isoformat()}#{self.id}"


# builds the right subclass from a stored item or an emitted payload
def parse_history_event(data: dict) -> HistoryEvent:
    event_type = data.get("event_type")
    cls = HistoryEvent.registry.get(event_type)
    if cls is None:
        raise ValueError(f"unknown event_type {event_type!r}")
    return cls.model_validate(data)
