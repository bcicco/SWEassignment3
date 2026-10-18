# saves and loads domain models using each type's schema (repo/schemas). Every write a
# command makes goes through one Transaction, so it either all happens or none of it does
from typing import TypeVar

from pydantic import BaseModel

from swe.domain.job import DeliveryJob, JobStateName
from swe.domain.request import DeliveryRequest, Quote, RequestStatus
from swe.domain.shared import HistoryEvent
from swe.infra.aws import client
from swe.infra.config import TABLE_NAME
from swe.repo.schema import Index, ItemSchema
from swe.repo.schemas import event_schema_for, schema_for
from swe.repo.schemas.job import DELIVERY_JOB, JOBS_BY_CUSTOMER, JOBS_BY_STATE
from swe.repo.schemas.request import BY_CUSTOMER, BY_STATUS, DELIVERY_REQUEST, QUOTE
from swe.repo.schemas.shared import HISTORY_EVENT

M = TypeVar("M", bound=BaseModel)


class NotFoundError(LookupError):
    pass


# another write changed the item since it was loaded (e.g. the quote was accepted twice)
class ConflictError(RuntimeError):
    pass


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
        expected = where or {}

        names = {f"#{k}": k for k in [*sets, *removes, *expected]}  # e.g. "status" is a reserved word
        values = {f":new_{k}": v for k, v in sets.items()}
        values |= {f":was_{k}": schema.encode(k, v) for k, v in expected.items() if v is not None}
        update = " ".join(
            filter(
                None,
                [
                    "SET " + ", ".join(f"#{k} = :new_{k}" for k in sets) if sets else "",
                    "REMOVE " + ", ".join(f"#{k}" for k in removes) if removes else "",
                ],
            )
        )
        # without attribute_exists, UpdateItem would create a missing item
        condition = " AND ".join(
            [
                "attribute_exists(pk)",
                *(f"attribute_not_exists(#{k})" if v is None else f"#{k} = :was_{k}" for k, v in expected.items()),
            ]
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

    def _get(self, schema: ItemSchema[M], **ids) -> M:
        key = schema.key(**ids)
        item = self._dynamodb.get_item(TableName=self._table, Key=key, ConsistentRead=True).get("Item")
        if item is None:
            raise NotFoundError(f"no {schema.model.__name__} at {key['pk']['S']} / {key['sk']['S']}")
        return schema.from_item(item)

    def get_request(self, request_id: str) -> DeliveryRequest:
        return self._get(DELIVERY_REQUEST, request_id=request_id)

    def get_quote(self, request_id: str, quote_id: str) -> Quote:
        return self._get(QUOTE, request_id=request_id, quote_id=quote_id)

    def get_job(self, job_id: str) -> DeliveryJob:
        return self._get(DELIVERY_JOB, job_id=job_id)

    # the items in a request's partition whose sort key starts with the schema's prefix
    def _query_partition(self, request_id: str, schema: ItemSchema) -> list[dict]:
        pages = self._dynamodb.get_paginator("query").paginate(
            TableName=self._table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": DELIVERY_REQUEST.key(request_id=request_id)["pk"],
                ":prefix": {"S": schema.sk_prefix},
            },
            ConsistentRead=True,
        )
        return [item for page in pages for item in page["Items"]]

    def list_quotes(self, request_id: str) -> list[Quote]:
        return [QUOTE.from_item(item) for item in self._query_partition(request_id, QUOTE)]

    # oldest first, since event sort keys lead with the timestamp
    def get_history(self, request_id: str) -> list[HistoryEvent]:
        return [event_schema_for(item).from_item(item) for item in self._query_partition(request_id, HISTORY_EVENT)]

    # newest first. Index reads can't be strongly consistent, so a request may take a
    # moment to appear here after it's logged; get_request always sees it
    def _query_index(self, index: Index, **values) -> list[dict]:
        pages = self._dynamodb.get_paginator("query").paginate(
            TableName=self._table,
            IndexName=index.name,
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": index.pk_attribute},
            ExpressionAttributeValues={":pk": {"S": index.pk.format(**values)}},
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

    def transaction(self) -> Transaction:
        return Transaction(self._dynamodb, self._table)
