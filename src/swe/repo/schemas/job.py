from swe.domain.job import Allocation, DeliveryJob, JobAllocated, JobCreated, JobStateName
from swe.repo.schema import Enum, Index, ItemSchema, Optional, String, Timestamp
from swe.repo.schemas.shared import HISTORY_EVENT

# a customer's jobs, and jobs in each state (e.g. unallocated ones awaiting a driver), newest first
JOBS_BY_CUSTOMER = Index("jobs_by_customer", pk="CUSTOMER#{customer_id}", sk="JOB#{created_at}")
JOBS_BY_STATE = Index("jobs_by_state", pk="JOB_STATE#{state}", sk="JOB#{created_at}")
# the jobs currently allocated to each driver; unallocated jobs are left out
JOBS_BY_DRIVER = Index("jobs_by_driver", pk="DRIVER#{delivery_staff_id}", sk="JOB#{created_at}")

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
        "allocation_id": Optional(String),
        "delivery_staff_id": Optional(String),
    },
    indexes=(JOBS_BY_CUSTOMER, JOBS_BY_STATE, JOBS_BY_DRIVER),
)

# a job's allocations live in its partition, oldest first
ALLOCATION = ItemSchema(
    Allocation,
    pk="JOB#{job_id}",
    sk="ALLOCATION#{created_at}#{id}",
    attributes={
        "id": String,
        "created_at": Timestamp,
        "created_by": Optional(String),
        "job_id": String,
        "delivery_staff_id": String,
        "replaces": Optional(String),
        "reason": Optional(String),
    },
)

JOB_CREATED = HISTORY_EVENT.extend(
    JobCreated,
    {
        "event_type": String,
        "job_id": String,
    },
)

JOB_ALLOCATED = HISTORY_EVENT.extend(
    JobAllocated,
    {
        "event_type": String,
        "job_id": String,
        "allocation_id": String,
        "delivery_staff_id": String,
        "previous_delivery_staff_id": Optional(String),
        "reason": Optional(String),
    },
)
