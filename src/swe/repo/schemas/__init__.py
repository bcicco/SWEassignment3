# every stored type's schema, found by model class (or by event_type for events)
from swe.domain.shared import HistoryEvent
from swe.repo.schema import ItemSchema
from swe.repo.schemas import job, request

SCHEMAS: dict[type, ItemSchema] = {
    schema.model: schema
    for schema in [
        request.DELIVERY_REQUEST,
        request.QUOTE,
        request.REQUEST_LOGGED,
        request.REQUEST_CANCELLED,
        request.QUOTE_ISSUED,
        request.QUOTE_ACCEPTED,
        request.QUOTE_REJECTED,
        job.DELIVERY_JOB,
    ]
}

EVENT_SCHEMAS: dict[str, ItemSchema] = {
    cls.TYPE: SCHEMAS[cls] for cls in HistoryEvent.registry.values() if cls in SCHEMAS
}


def schema_for(model: type | object) -> ItemSchema:
    cls = model if isinstance(model, type) else type(model)
    if cls not in SCHEMAS:
        raise LookupError(f"no schema for {cls.__name__}")
    return SCHEMAS[cls]


# a stored or streamed history event item, chosen by its event_type
def event_schema_for(item: dict) -> ItemSchema:
    event_type = item.get("event_type", {}).get("S")
    if event_type not in EVENT_SCHEMAS:
        raise ValueError(f"no schema for event_type {event_type!r}")
    return EVENT_SCHEMAS[event_type]
