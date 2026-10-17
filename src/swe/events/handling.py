import functools

from swe.domain.shared import HistoryEvent, parse_history_event


# Declares which events a handler accepts, and turns the handler into a Lambda.
#
# EventBridge invokes the Lambda with its own wrapper around our event, which sits
# in detail... this unwraps it into the right HistoryEvent subclass and passes only
# that to the handler. event_types becomes the handler's EventBridge rule, and
# None means every event.
def handles(*event_classes: type[HistoryEvent]):
    def wrap(handler):
        @functools.wraps(handler)
        def lambda_handler(raw: dict, context=None) -> None:
            event = parse_history_event(raw["detail"])
            if event_classes and not isinstance(event, event_classes):
                raise TypeError(f"{handler.__name__} doesn't handle {event.event_type}")
            handler(event)

        lambda_handler.event_types = [c.TYPE for c in event_classes] or None
        return lambda_handler

    return wrap
