from swe.domain.request import (
    DeliveryRequest,
    Quote,
    QuoteAccepted,
    QuoteIssued,
    QuoteRejected,
    QuoteStatus,
    RequestCancelled,
    RequestLogged,
    RequestStatus,
)
from swe.repo.schema import Enum, Index, ItemSchema, List, Number, Optional, String, Timestamp, Window
from swe.repo.schemas.shared import ADDRESS, HISTORY_EVENT, PARCEL

# a customer's requests, and requests in each status (e.g. open ones awaiting a quote), newest first
BY_CUSTOMER = Index("by_customer", pk="CUSTOMER#{customer_id}", sk="REQUEST#{created_at}")
BY_STATUS = Index("by_status", pk="REQUEST_STATUS#{status}", sk="REQUEST#{created_at}")

DELIVERY_REQUEST = ItemSchema(
    DeliveryRequest,
    pk="REQUEST#{request_id}",
    sk="METADATA",
    attributes={
        "request_id": String,
        "created_at": Timestamp,
        "customer_id": Optional(String),
        "logged_by": Optional(String),
        "contact_name": String,
        "contact_phone": String,
        "parcels": List(PARCEL),
        "pickup_address": ADDRESS,
        "dropoff_address": ADDRESS,
        "status": Enum(RequestStatus),
        "current_quote_id": Optional(String),
    },
    indexes=(BY_CUSTOMER, BY_STATUS),
)

# quotes live in their request's partition
QUOTE = ItemSchema(
    Quote,
    pk="REQUEST#{request_id}",
    sk="QUOTE#{quote_id}",
    attributes={
        "request_id": String,
        "quote_id": String,
        "price": Number,
        "eta_pickup": Window,
        "eta_dropoff": Window,
        "time_of_issue": Timestamp,
        "expiry_time": Timestamp,
        "issued_by": String,
        "status": Enum(QuoteStatus),
        "responded_by": Optional(String),
        "responded_at": Optional(Timestamp),
    },
)

REQUEST_LOGGED = HISTORY_EVENT.extend(
    RequestLogged,
    {
        "event_type": String,
        "customer_id": Optional(String),
        "logged_by": Optional(String),
    },
)

REQUEST_CANCELLED = HISTORY_EVENT.extend(
    RequestCancelled,
    {
        "event_type": String,
    },
)

QUOTE_ISSUED = HISTORY_EVENT.extend(
    QuoteIssued,
    {
        "event_type": String,
        "quote_id": String,
        "price": Number,
        "expiry_time": Timestamp,
        "supersedes": Optional(String),
    },
)

QUOTE_ACCEPTED = HISTORY_EVENT.extend(
    QuoteAccepted,
    {
        "event_type": String,
        "quote_id": String,
        "job_id": String,
    },
)

QUOTE_REJECTED = HISTORY_EVENT.extend(
    QuoteRejected,
    {
        "event_type": String,
        "quote_id": String,
    },
)
