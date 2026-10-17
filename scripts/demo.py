# writes a request, quote and acceptance to the table so the pipeline has events to route
from datetime import datetime, timedelta
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer

from swe.domain.request import DeliveryRequest
from swe.domain.shared.ids import now
from swe.infra.aws import client
from swe.infra.config import TABLE_NAME

serializer = TypeSerializer()


def plain(value):
    # DynamoDB has no datetime or tuple types
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if v is not None}
    return value


def put(dynamodb, *models) -> None:
    for model in models:
        item = {k: serializer.serialize(v) for k, v in plain(model.model_dump()).items()}
        dynamodb.put_item(TableName = TABLE_NAME, Item = item)


def main() -> None:
    dynamodb = client("dynamodb")
    t = now()
    request, logged = DeliveryRequest.log(
        customer_id = "cust-1", contact_name = "Sam", contact_phone = "0400000000",
        parcels = [{"size": "small", "weight_kg": "2.5"}],
        pickup_address = {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
        dropoff_address = {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
    )
    put(dynamodb, request, logged)

    quote, issued = request.issue_quote(
        price = Decimal("50"), valid_for = timedelta(hours = 24), issued_by = "staff-1", previous = None,
        eta_pickup = (t + timedelta(hours = 1), t + timedelta(hours = 3)),
        eta_dropoff = (t + timedelta(hours = 4), t + timedelta(hours = 6)),
    )
    put(dynamodb, request, quote, *issued)

    # not yet the conditional transaction the repo layer will need
    job, accepted = request.accept_quote(quote, by = "cust-1")
    put(dynamodb, request, quote, job, accepted)
    print(f"wrote request {request.request_id}, quote {quote.quote_id}, job {job.job_id}")


if __name__ == "__main__":
    main()
