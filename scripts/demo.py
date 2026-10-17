# runs the request → quote → accept flow through the commands, so the pipeline has events to route
from datetime import timedelta
from decimal import Decimal

from swe.app import AcceptQuote, DeliveryManagementSystem, IssueQuote, LogRequest
from swe.domain.shared.ids import now


def main() -> None:
    dms = DeliveryManagementSystem()
    t = now()
    request = dms.log_request(LogRequest(
        customer_id = "cust-1", contact_name = "Sam", contact_phone = "0400000000",
        parcels = [{"size": "small", "weight_kg": "2.5"}],
        pickup_address = {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
        dropoff_address = {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
    ))
    quote = dms.issue_quote(IssueQuote(
        request_id = request.request_id, staff_id = "staff-1", price = Decimal("50"),
        eta_pickup = (t + timedelta(hours = 1), t + timedelta(hours = 3)),
        eta_dropoff = (t + timedelta(hours = 4), t + timedelta(hours = 6)),
    ))
    job = dms.accept_quote(AcceptQuote(request_id = request.request_id, quote_id = quote.quote_id, customer_id = "cust-1"))
    print(f"request {request.request_id}, quote {quote.quote_id}, job {job.job_id}")


if __name__ == "__main__":
    main()
