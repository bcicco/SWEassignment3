from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import BaseModel

from swe.domain.request import DeliveryRequest
from swe.domain.shared import HistoryEvent
from swe.domain.shared.ids import now
from swe.repo.schema import ItemSchema, Optional, String
from swe.repo.schemas import EVENT_SCHEMAS, event_schema_for, schema_for
from swe.repo.schemas.job import DELIVERY_JOB
from swe.repo.schemas.request import DELIVERY_REQUEST, QUOTE, QUOTE_ISSUED

T = now()
DETAILS = dict(
    customer_id = "cust-1", contact_name = "Sam", contact_phone = "0400000000",
    parcels = [{"size": "small", "weight_kg": "2.5", "quantity": 2}],
    pickup_address = {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
    dropoff_address = {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
)


def flow():
    request, logged = DeliveryRequest.log(**DETAILS)
    q1, issued1 = request.issue_quote(
        price = Decimal("50.25"), valid_for = timedelta(hours = 24), issued_by = "staff-1", previous = None, at = T,
        eta_pickup = (T + timedelta(hours = 1), T + timedelta(hours = 3)),
        eta_dropoff = (T + timedelta(hours = 4), T + timedelta(hours = 6)),
    )
    q2, issued2 = request.issue_quote(
        price = Decimal("45"), valid_for = timedelta(hours = 24), issued_by = "staff-1", previous = q1, at = T,
        eta_pickup = (T + timedelta(hours = 1), T + timedelta(hours = 3)),
        eta_dropoff = (T + timedelta(hours = 4), T + timedelta(hours = 6)),
    )
    job, accepted = request.accept_quote(q2, by = "cust-1", at = T)
    return request, [q1, q2], job, [logged, issued1, issued2, accepted]


def test_every_event_type_has_a_schema():
    assert set(EVENT_SCHEMAS) == set(HistoryEvent.registry)


def test_every_model_round_trips():
    request, quotes, job, events = flow()
    for model in [request, *quotes, job, *events]:
        schema = schema_for(model)
        assert schema.from_item(schema.to_item(model)) == model


def test_items_use_dynamodb_types():
    request, (q1, _), _, _ = flow()
    item = QUOTE.to_item(q1)
    assert item["pk"] == {"S": f"REQUEST#{request.request_id}"}
    assert item["sk"] == {"S": f"QUOTE#{q1.quote_id}"}
    assert item["price"] == {"N": "50.25"}
    assert item["status"] == {"S": "superseded"}
    assert item["eta_pickup"] == {"L": [{"S": q1.eta_pickup[0].isoformat()}, {"S": q1.eta_pickup[1].isoformat()}]}
    assert "responded_by" not in item # None is left off

    stored = DELIVERY_REQUEST.to_item(request)
    assert stored["parcels"]["L"][0] == {"M": {"size": {"S": "small"}, "weight_kg": {"N": "2.5"}, "quantity": {"N": "2"}}}


def test_keys():
    request, _, job, _ = flow()
    assert DELIVERY_REQUEST.key(request_id = "r1") == {"pk": {"S": "REQUEST#r1"}, "sk": {"S": "METADATA"}}
    assert DELIVERY_JOB.key_of(job)["pk"] == {"S": f"JOB#{job.job_id}"}


def test_event_sort_key_leads_with_timestamp():
    _, _, _, events = flow()
    issued = events[1]
    assert QUOTE_ISSUED.key_of(issued)["sk"] == {"S": f"EVENT#{T.isoformat()}#{issued.id}"}


def test_event_schema_chosen_by_type():
    _, _, _, events = flow()
    accepted = events[-1]
    item = schema_for(accepted).to_item(accepted)
    assert event_schema_for(item).from_item(item) == accepted
    with pytest.raises(ValueError, match = "no schema for event_type"):
        event_schema_for({"event_type": {"S": "nope"}})


def test_schema_must_match_model_fields():
    class Thing(BaseModel):
        name: str
        note: str | None = None

    with pytest.raises(TypeError, match = r"missing \['note'\]"):
        ItemSchema(Thing, pk = "THING#{name}", sk = "METADATA", attributes = {"name": String})
    with pytest.raises(TypeError, match = r"extra \['nmae'\]"):
        ItemSchema(Thing, pk = "THING#{name}", sk = "METADATA", attributes = {"name": String, "note": Optional(String), "nmae": String})


def test_missing_required_attribute_is_refused():
    request, _, _, _ = flow()
    item = DELIVERY_REQUEST.to_item(request)
    del item["contact_name"]
    with pytest.raises(ValueError, match = "missing contact_name"):
        DELIVERY_REQUEST.from_item(item)
