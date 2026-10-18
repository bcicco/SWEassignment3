from swe.domain.job import DeliveryJob, JobStateName
from swe.repo.schema import Enum, Index, ItemSchema, String, Timestamp

# a customer's jobs, and jobs in each state (e.g. unallocated ones awaiting a driver), newest first
JOBS_BY_CUSTOMER = Index("jobs_by_customer", pk="CUSTOMER#{customer_id}", sk="JOB#{created_at}")
JOBS_BY_STATE = Index("jobs_by_state", pk="JOB_STATE#{state}", sk="JOB#{created_at}")

DELIVERY_JOB = ItemSchema(
    DeliveryJob,
    pk="JOB#{job_id}",
    sk="METADATA",
    attributes={
        "job_id": String,
        "request_id": String,
        "quote_id": String,
        "customer_id": String,
        "created_at": Timestamp,
        "state": Enum(JobStateName),
    },
    indexes=(JOBS_BY_CUSTOMER, JOBS_BY_STATE),
)
