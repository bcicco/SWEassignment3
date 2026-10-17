# Lambda on the table's DynamoDB stream: publishes each new HistoryEvent to the bus.
# If publishing fails the whole batch is retried, so events are at-least-once.
import logging

from swe.infra.aws import client
from swe.infra.config import EVENT_BUS_NAME, EVENT_SOURCE
from swe.repo.schemas import event_schema_for

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def to_event(record: dict) -> dict | None:
    # only appended history events are domain events; everything else is state
    if record["eventName"] != "INSERT":
        return None
    item = record["dynamodb"]["NewImage"]
    if not item["sk"]["S"].startswith("EVENT#"):
        return None
    try:
        event = event_schema_for(item).from_item(item)
    except ValueError:  # includes pydantic ValidationError
        # skip rather than block the shard; the item is still in the table to fix and replay
        log.exception("unreadable history event %s %s", item["pk"]["S"], item["sk"]["S"])
        return None
    return {
        "Source": EVENT_SOURCE,
        "DetailType": event.event_type,
        "Detail": event.model_dump_json(),
        "EventBusName": EVENT_BUS_NAME,
    }


def publish(events, entries: list[dict]) -> None:
    for i in range(0, len(entries), 10):  # PutEvents takes at most 10
        result = events.put_events(Entries=entries[i : i + 10])
        if result["FailedEntryCount"]:
            raise RuntimeError(f"put_events failed: {result['Entries']}")


def handler(event: dict, context=None) -> None:
    entries = [e for e in map(to_event, event["Records"]) if e]
    if entries:
        publish(client("events"), entries)
        log.info("published %s", [e["DetailType"] for e in entries])
