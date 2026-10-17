from swe.domain.shared import Address, HistoryEvent, Parcel, ParcelSize
from swe.repo.schema import Enum, ItemSchema, Map, Number, Optional, String, Timestamp

# data holders, stored inside their owner's item

ADDRESS = Map(
    Address,
    {
        "street": String,
        "suburb": String,
        "postcode": String,
    },
)

PARCEL = Map(
    Parcel,
    {
        "size": Enum(ParcelSize),
        "weight_kg": Number,
        "quantity": Number,
    },
)

# every event lives in its request's partition. The timestamp leads the sort key so a
# request's history reads back in order
HISTORY_EVENT = ItemSchema(
    HistoryEvent,
    pk="REQUEST#{request_id}",
    sk="EVENT#{created_at}#{id}",
    attributes={
        "id": String,
        "created_at": Timestamp,
        "created_by": Optional(String),
        "request_id": String,
    },
)
