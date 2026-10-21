# saves and loads domain models using each type's schema (repo/schemas). Every write a
# command makes goes through one Transaction, so it either all happens or none of it does
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from swe.domain.job import Allocation, DeliveryJob, JobStateName, Payment, PaymentAdjustment, Settlement
from swe.domain.job.execution_state import ExecutionProgress
from swe.domain.request import DeliveryRequest, Quote, RequestStatus
from swe.domain.shared import HistoryEvent
from swe.domain.user import AvailabilitySlot, DeliveryStaff, User
from swe.infra.aws import client
from swe.infra.config import TABLE_NAME
from swe.repo.schema import Index, ItemSchema
from swe.repo.schemas import event_schema_for, schema_for, user_schema_for
from swe.repo.schemas.execution import PROGRESS
from swe.repo.schemas.job import (
    ALLOCATION,
    COLLECTIONS_BY_STAFF,
    DELIVERY_JOB,
    JOBS_BY_CUSTOMER,
    JOBS_BY_DRIVER,
    JOBS_BY_STATE,
    PAYMENT,
    PAYMENT_ADJUSTMENT,
    SETTLEMENT,
)
from swe.repo.schemas.request import BY_CUSTOMER, BY_STATUS, DELIVERY_REQUEST, QUOTE
from swe.repo.schemas.shared import HISTORY_EVENT
from swe.repo.schemas.user import AVAILABILITY_SLOT, DELIVERY_STAFF, USER, USERS_BY_KIND

M = TypeVar("M", bound=BaseModel)


class NotFoundError(LookupError):
    pass


# another write changed the item since it was loaded (e.g. the quote was accepted twice)
class ConflictError(RuntimeError):
    pass


# the condition that each attribute in `expected` still holds the value a decision was based
# on (None means still absent), with its placeholder names and values
def _guard(schema: ItemSchema, expected: dict) -> tuple[str, dict, dict]:
    names = {f"#{k}": k for k in expected}
    values = {f":was_{k}": schema.encode(k, v) for k, v in expected.items() if v is not None}
    # without attribute_exists, UpdateItem would create a missing item
    condition = " AND ".join(
        [
            "attribute_exists(pk)",
            *(f"attribute_not_exists(#{k})" if v is None else f"#{k} = :was_{k}" for k, v in expected.items()),
        ]
    )
    return condition, names, values


class Transaction:
    def __init__(self, dynamodb, table: str):
        self._dynamodb, self._table = dynamodb, table
        self._items: list[dict] = []

    # a new item; fails if one already exists with the same key
    def create(self, model: BaseModel) -> "Transaction":
        self._items.append(
            {
                "Put": {
                    "TableName": self._table,
                    "Item": schema_for(model).to_item(model),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        )
        return self

    # writes only the listed fields of an item loaded earlier. `where` guards against
    # concurrent changes: each attribute must still hold the value the decision was based
    # on (None means still absent), or the whole transaction fails
    def update(self, model: BaseModel, fields: list[str], where: dict | None = None) -> "Transaction":
        schema = schema_for(model)
        unknown = set(fields) - set(schema.attributes)
        if unknown:
            raise ValueError(f"{type(model).__name__} has no fields {sorted(unknown)}")
        sets = {f: schema.encode(f, getattr(model, f)) for f in fields if getattr(model, f) is not None}
        removes = [f for f in fields if getattr(model, f) is None]  # None values aren't stored
        # an index whose key uses a changed field is rewritten with it, e.g. by_status on cancel
        for index in schema.indexes:
            if index.fields & set(fields):
                index_key = schema.index_key_of(index, model)
                if index_key:
                    sets |= index_key
                else:
                    removes += [index.pk_attribute, index.sk_attribute]
        condition, guard_names, guard_values = _guard(schema, where or {})

        names = {f"#{k}": k for k in [*sets, *removes]} | guard_names  # e.g. "status" is a reserved word
        values = {f":new_{k}": v for k, v in sets.items()} | guard_values
        update = " ".join(
            filter(
                None,
                [
                    "SET " + ", ".join(f"#{k} = :new_{k}" for k in sets) if sets else "",
                    "REMOVE " + ", ".join(f"#{k}" for k in removes) if removes else "",
                ],
            )
        )
        update_item = {
            "TableName": self._table,
            "Key": schema.key_of(model),
            "UpdateExpression": update,
            "ConditionExpression": condition,
            "ExpressionAttributeNames": names,
        }
        if values:
            update_item["ExpressionAttributeValues"] = values
        self._items.append({"Update": update_item})
        return self

    # writes nothing, but fails the whole transaction unless an item loaded earlier still
    # matches `where`, e.g. that the job is still allocated to the driver recording a payment
    def check(self, model: BaseModel, where: dict) -> "Transaction":
        schema = schema_for(model)
        condition, names, values = _guard(schema, where)
        check = {
            "TableName": self._table,
            "Key": schema.key_of(model),
            "ConditionExpression": condition,
            "ExpressionAttributeNames": names,
        }
        if values:
            check["ExpressionAttributeValues"] = values
        self._items.append({"ConditionCheck": check})
        return self

    # removes an item loaded earlier; fails if it's already gone
    def delete(self, model: BaseModel) -> "Transaction":
        self._items.append(
            {
                "Delete": {
                    "TableName": self._table,
                    "Key": schema_for(model).key_of(model),
                    "ConditionExpression": "attribute_exists(pk)",
                }
            }
        )
        return self

    def commit(self) -> None:
        try:
            self._dynamodb.transact_write_items(TransactItems=self._items)
        except self._dynamodb.exceptions.TransactionCanceledException as e:
            reasons = [r.get("Code") for r in e.response.get("CancellationReasons", [])]
            if "ConditionalCheckFailed" in reasons:
                raise ConflictError("the data changed since it was loaded; reload and retry") from e
            raise


class Repository:
    def __init__(self, dynamodb=None, table: str = TABLE_NAME):
        self._dynamodb = dynamodb or client("dynamodb")
        self._table = table

    def _get_item(self, schema: ItemSchema, **ids) -> dict:
        key = schema.key(**ids)
        item = self._dynamodb.get_item(TableName=self._table, Key=key, ConsistentRead=True).get("Item")
        if item is None:
            raise NotFoundError(f"no {schema.model.__name__} at {key['pk']['S']} / {key['sk']['S']}")
        return item

    def _get(self, schema: ItemSchema[M], **ids) -> M:
        return schema.from_item(self._get_item(schema, **ids))

    def get_request(self, request_id: str) -> DeliveryRequest:
        return self._get(DELIVERY_REQUEST, request_id=request_id)

    def get_quote(self, request_id: str, quote_id: str) -> Quote:
        return self._get(QUOTE, request_id=request_id, quote_id=quote_id)

    def get_job(self, job_id: str) -> DeliveryJob:
        return self._get(DELIVERY_JOB, job_id=job_id)

    # a Customer, StaffMember or DeliveryStaff, whichever the stored kind is
    def get_user(self, user_id: str) -> User:
        item = self._get_item(USER, user_id=user_id)
        return user_schema_for(item).from_item(item)

    # the items in a partition (e.g. a request's) whose sort key starts with the schema's prefix
    def _query_partition(self, pk: dict, schema: ItemSchema) -> list[dict]:
        pages = self._dynamodb.get_paginator("query").paginate(
            TableName=self._table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": pk,
                ":prefix": {"S": schema.sk_prefix},
            },
            ConsistentRead=True,
        )
        return [item for page in pages for item in page["Items"]]

    def list_quotes(self, request_id: str) -> list[Quote]:
        items = self._query_partition(DELIVERY_REQUEST.key(request_id=request_id)["pk"], QUOTE)
        return [QUOTE.from_item(item) for item in items]

    # oldest first, since event sort keys lead with the timestamp
    def get_history(self, request_id: str) -> list[HistoryEvent]:
        items = self._query_partition(DELIVERY_REQUEST.key(request_id=request_id)["pk"], HISTORY_EVENT)
        return [event_schema_for(item).from_item(item) for item in items]

    # newest first. Index reads can't be strongly consistent, so a request may take a
    # moment to appear here after it's logged; get_request always sees it
    # `between` limits it to index sort keys in that inclusive range
    def _query_index(self, index: Index, between: tuple[str, str] | None = None, **values) -> list[dict]:
        condition = "#pk = :pk"
        names = {"#pk": index.pk_attribute}
        attribute_values = {":pk": {"S": index.pk.format(**values)}}
        if between:
            condition += " AND #sk BETWEEN :from AND :to"
            names["#sk"] = index.sk_attribute
            attribute_values |= {":from": {"S": between[0]}, ":to": {"S": between[1]}}
        pages = self._dynamodb.get_paginator("query").paginate(
            TableName=self._table,
            IndexName=index.name,
            KeyConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=attribute_values,
            ScanIndexForward=False,
        )
        return [item for page in pages for item in page["Items"]]

    def list_customer_requests(self, customer_id: str) -> list[DeliveryRequest]:
        return [DELIVERY_REQUEST.from_item(i) for i in self._query_index(BY_CUSTOMER, customer_id=customer_id)]

    def list_requests_by_status(self, status: RequestStatus) -> list[DeliveryRequest]:
        return [DELIVERY_REQUEST.from_item(i) for i in self._query_index(BY_STATUS, status=status)]

    def list_customer_jobs(self, customer_id: str) -> list[DeliveryJob]:
        return [DELIVERY_JOB.from_item(i) for i in self._query_index(JOBS_BY_CUSTOMER, customer_id=customer_id)]

    def list_jobs_by_state(self, state: JobStateName) -> list[DeliveryJob]:
        return [DELIVERY_JOB.from_item(i) for i in self._query_index(JOBS_BY_STATE, state=state)]

    # the jobs a driver currently holds the active Allocation for
    def list_driver_jobs(self, delivery_staff_id: str) -> list[DeliveryJob]:
        items = self._query_index(JOBS_BY_DRIVER, delivery_staff_id=delivery_staff_id)
        return [DELIVERY_JOB.from_item(i) for i in items]

    # oldest first, so the last is the active one
    def list_allocations(self, job_id: str) -> list[Allocation]:
        items = self._query_partition(DELIVERY_JOB.key(job_id=job_id)["pk"], ALLOCATION)
        return [ALLOCATION.from_item(item) for item in items]

    def get_settlement(self, job_id: str) -> Settlement:
        return self._get(SETTLEMENT, job_id=job_id)

    def get_payment(self, job_id: str, payment_id: str) -> Payment:
        return self._get(PAYMENT, job_id=job_id, id=payment_id)

    def get_adjustment(self, job_id: str, adjustment_id: str) -> PaymentAdjustment:
        return self._get(PAYMENT_ADJUSTMENT, job_id=job_id, id=adjustment_id)

    def list_payments(self, job_id: str) -> list[Payment]:
        items = self._query_partition(DELIVERY_JOB.key(job_id=job_id)["pk"], PAYMENT)
        return sorted((PAYMENT.from_item(i) for i in items), key=lambda p: p.created_at)

    def list_adjustments(self, job_id: str) -> list[PaymentAdjustment]:
        items = self._query_partition(DELIVERY_JOB.key(job_id=job_id)["pk"], PAYMENT_ADJUSTMENT)
        return sorted((PAYMENT_ADJUSTMENT.from_item(i) for i in items), key=lambda a: a.created_at)

    # the payments and adjustments one person recorded in [start, end), oldest first
    def list_collections(
        self, staff_id: str, start: datetime, end: datetime
    ) -> tuple[list[Payment], list[PaymentAdjustment]]:
        # a key at exactly `end` sorts after this bound, since it continues with "#<id>"
        between = (f"MONEY#{start.isoformat()}", f"MONEY#{end.isoformat()}")
        items = self._query_index(COLLECTIONS_BY_STAFF, between=between, created_by=staff_id)
        payments = [PAYMENT.from_item(i) for i in items if i["sk"]["S"].startswith(PAYMENT.sk_prefix)]
        adjustments = [
            PAYMENT_ADJUSTMENT.from_item(i) for i in items if i["sk"]["S"].startswith(PAYMENT_ADJUSTMENT.sk_prefix)
        ]
        return sorted(payments, key=lambda p: p.created_at), sorted(adjustments, key=lambda a: a.created_at)

    # None until the job's first execution update
    def get_execution_progress(self, job_id: str) -> ExecutionProgress | None:
        try:
            return self._get(PROGRESS, job_id=job_id)
        except NotFoundError:
            return None

    # earliest first, since slot sort keys lead with the start time
    def list_slots(self, delivery_staff_id: str) -> list[AvailabilitySlot]:
        items = self._query_partition(USER.key(user_id=delivery_staff_id)["pk"], AVAILABILITY_SLOT)
        return [AVAILABILITY_SLOT.from_item(item) for item in items]

    def list_delivery_staff(self) -> list[DeliveryStaff]:
        kind = DeliveryStaff.model_fields["kind"].default
        return [DELIVERY_STAFF.from_item(i) for i in self._query_index(USERS_BY_KIND, kind=kind)]

    def transaction(self) -> Transaction:
        return Transaction(self._dynamodb, self._table)
