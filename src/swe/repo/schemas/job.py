from swe.domain.job import (
    Allocation,
    DeliveryJob,
    JobAllocated,
    JobClosed,
    JobCreated,
    JobStateName,
    Payment,
    PaymentAdjusted,
    PaymentAdjustment,
    PaymentMethod,
    PaymentOutcome,
    PaymentRecorded,
    Settlement,
)
from swe.repo.schema import Enum, Index, ItemSchema, Number, Optional, String, Timestamp
from swe.repo.schemas.shared import HISTORY_EVENT

# a customer's jobs, and jobs in each state (e.g. unallocated ones awaiting a driver), newest first
JOBS_BY_CUSTOMER = Index("jobs_by_customer", pk="CUSTOMER#{customer_id}", sk="JOB#{created_at}")
JOBS_BY_STATE = Index("jobs_by_state", pk="JOB_STATE#{state}", sk="JOB#{created_at}")
# the jobs currently allocated to each driver; unallocated jobs are left out
JOBS_BY_DRIVER = Index("jobs_by_driver", pk="DRIVER#{delivery_staff_id}", sk="JOB#{created_at}")
# the money each person took, payments and adjustments together, in time order for daily
# totals (QA3.6). The collector is the record's created_by
COLLECTIONS_BY_STAFF = Index("collections_by_staff", pk="COLLECTOR#{created_by}", sk="MONEY#{created_at}#{id}")

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

# a job's payments, adjustments and settlement live in its partition
PAYMENT = ItemSchema(
    Payment,
    pk="JOB#{job_id}",
    sk="PAYMENT#{id}",
    attributes={
        "id": String,
        "created_at": Timestamp,
        "created_by": Optional(String),
        "job_id": String,
        "quote_id": String,
        "outcome": Enum(PaymentOutcome),
        "method": Optional(Enum(PaymentMethod)),
        "amount_due": Number,
        "amount": Number,
        "reason": Optional(String),
    },
    indexes=(COLLECTIONS_BY_STAFF,),
)

PAYMENT_ADJUSTMENT = ItemSchema(
    PaymentAdjustment,
    pk="JOB#{job_id}",
    sk="ADJUSTMENT#{id}",
    attributes={
        "id": String,
        "created_at": Timestamp,
        "created_by": Optional(String),
        "job_id": String,
        "payment_id": String,
        "amount": Number,
        "method": Enum(PaymentMethod),
        "provider_reference": Optional(String),
        "reason": String,
    },
    indexes=(COLLECTIONS_BY_STAFF,),
)

SETTLEMENT = ItemSchema(
    Settlement,
    pk="JOB#{job_id}",
    sk="SETTLEMENT",
    attributes={
        "job_id": String,
        "amount_due": Number,
        "net_collected": Number,
        "revision": Number,
    },
)

PAYMENT_RECORDED = HISTORY_EVENT.extend(
    PaymentRecorded,
    {
        "event_type": String,
        "job_id": String,
        "payment_id": String,
        "outcome": Enum(PaymentOutcome),
        "method": Optional(Enum(PaymentMethod)),
        "amount": Number,
        "amount_due": Number,
        "outstanding": Number,
    },
)

PAYMENT_ADJUSTED = HISTORY_EVENT.extend(
    PaymentAdjusted,
    {
        "event_type": String,
        "job_id": String,
        "adjustment_id": String,
        "payment_id": String,
        "amount": Number,
        "method": Enum(PaymentMethod),
        "outstanding": Number,
    },
)

JOB_CLOSED = HISTORY_EVENT.extend(
    JobClosed,
    {
        "event_type": String,
        "job_id": String,
    },
)
