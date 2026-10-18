# single source of truth for EventBridge rules: bootstrap deploys each handler as a
# Lambda and creates a rule from its @handles declaration that targets it
from swe.events import handlers

ROUTES = {
    "create-delivery-job": handlers.create_delivery_job,
    "notify-office-staff": handlers.notify_office_staff,
    "notify-customer": handlers.notify_customer,
    "notify-driver": handlers.notify_driver,
    "audit": handlers.audit,
}


def function_name(route: str) -> str:
    return f"yowd-{route}"


# the dotted path Lambda imports, e.g. swe.events.handlers.audit
def handler_path(route: str) -> str:
    handler = ROUTES[route]
    return f"{handler.__module__}.{handler.__name__}"
