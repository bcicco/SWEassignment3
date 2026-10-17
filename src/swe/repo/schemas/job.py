from swe.domain.job import DeliveryJob, JobStateName
from swe.repo.schema import Enum, ItemSchema, String, Timestamp

DELIVERY_JOB = ItemSchema(
    DeliveryJob,
    pk = "JOB#{job_id}",
    sk = "METADATA",
    attributes = {
        "job_id": String,
        "request_id": String,
        "quote_id": String,
        "created_at": Timestamp,
        "state": Enum(JobStateName),
    },
)
