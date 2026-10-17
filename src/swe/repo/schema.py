# how a model is stored as a DynamoDB item: one codec per attribute, plus key templates.
# Codecs write DynamoDB's attribute-value format directly, e.g. {"S": "..."} or {"N": "50"}
from datetime import datetime
from decimal import Decimal
from enum import Enum as _Enum
from typing import Generic, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound = BaseModel)


class Codec:
    optional = False

    def encode(self, value) -> dict:
        raise NotImplementedError

    def decode(self, attribute: dict):
        raise NotImplementedError

    # the value substituted into key templates
    def key_part(self, value):
        return value


class _String(Codec):
    def encode(self, value: str) -> dict:
        return {"S": value}

    def decode(self, attribute: dict) -> str:
        return attribute["S"]


class _Number(Codec):
    def encode(self, value: int | Decimal) -> dict:
        return {"N": str(value)}

    def decode(self, attribute: dict) -> Decimal:
        return Decimal(attribute["N"])


# stored as an ISO 8601 string, so timestamps sort correctly as text
class _Timestamp(Codec):
    def encode(self, value: datetime) -> dict:
        return {"S": value.isoformat()}

    def decode(self, attribute: dict) -> datetime:
        return datetime.fromisoformat(attribute["S"])

    def key_part(self, value: datetime) -> str:
        return value.isoformat()


# a (start, end) pair of timestamps
class _Window(Codec):
    def encode(self, value: tuple[datetime, datetime]) -> dict:
        return {"L": [Timestamp.encode(v) for v in value]}

    def decode(self, attribute: dict) -> tuple[datetime, datetime]:
        start, end = (Timestamp.decode(v) for v in attribute["L"])
        return start, end


String, Number, Timestamp, Window = _String(), _Number(), _Timestamp(), _Window()


class Enum(Codec):
    def __init__(self, enum: type[_Enum]):
        self.enum = enum

    def encode(self, value: _Enum) -> dict:
        return {"S": self.enum(value).value}

    def decode(self, attribute: dict) -> _Enum:
        return self.enum(attribute["S"])


# may be None, in which case the attribute is left off the item
class Optional(Codec):
    optional = True

    def __init__(self, codec: Codec):
        self.codec = codec

    def encode(self, value) -> dict:
        return self.codec.encode(value)

    def decode(self, attribute: dict):
        return self.codec.decode(attribute)


def _check_matches(model: type[BaseModel], attributes: dict[str, Codec]) -> None:
    missing = set(model.model_fields) - set(attributes)
    extra = set(attributes) - set(model.model_fields)
    if missing or extra:
        raise TypeError(f"schema for {model.__name__} doesn't match its fields: missing {sorted(missing)}, extra {sorted(extra)}")


def _encode_attributes(attributes: dict[str, Codec], model: BaseModel) -> dict:
    encoded = {}
    for name, codec in attributes.items():
        value = getattr(model, name)
        if value is None:
            if not codec.optional:
                raise ValueError(f"{type(model).__name__}.{name} is None but isn't Optional in its schema")
            continue
        encoded[name] = codec.encode(value)
    return encoded


def _decode_attributes(attributes: dict[str, Codec], model: type[BaseModel], item: dict) -> dict:
    decoded = {}
    for name, codec in attributes.items():
        if name in item:
            decoded[name] = codec.decode(item[name])
        elif not codec.optional:
            raise ValueError(f"stored {model.__name__} is missing {name}")
    return decoded


# a data holder stored inside its owner's item, e.g. an Address
class Map(Codec):
    def __init__(self, model: type[BaseModel], attributes: dict[str, Codec]):
        _check_matches(model, attributes)
        self.model, self.attributes = model, attributes

    def encode(self, value: BaseModel) -> dict:
        return {"M": _encode_attributes(self.attributes, value)}

    def decode(self, attribute: dict) -> BaseModel:
        return self.model.model_validate(_decode_attributes(self.attributes, self.model, attribute["M"]))


class List(Codec):
    def __init__(self, codec: Codec):
        self.codec = codec

    def encode(self, value: list) -> dict:
        return {"L": [self.codec.encode(v) for v in value]}

    def decode(self, attribute: dict) -> list:
        return [self.codec.decode(v) for v in attribute["L"]]


# One stored type. pk and sk are templates filled from the model's attributes, e.g.
# "QUOTE#{quote_id}"; format specs such as {n:02d} work too
class ItemSchema(Generic[M]):
    def __init__(self, model: type[M], *, pk: str, sk: str, attributes: dict[str, Codec]):
        _check_matches(model, attributes)
        self.model, self.pk, self.sk, self.attributes = model, pk, sk, attributes

    # the same keys and attributes plus extra ones, for subclasses such as each event
    def extend(self, model: type[M], attributes: dict[str, Codec]) -> "ItemSchema[M]":
        return ItemSchema(model, pk = self.pk, sk = self.sk, attributes = self.attributes | attributes)

    # build a key from the identifying values, e.g. key(request_id = ..., quote_id = ...)
    def key(self, **values) -> dict:
        return {"pk": {"S": self.pk.format(**values)}, "sk": {"S": self.sk.format(**values)}}

    def key_of(self, model: M) -> dict:
        return self.key(**{name: codec.key_part(getattr(model, name)) for name, codec in self.attributes.items()})

    # one attribute's stored form, for updates and conditions
    def encode(self, name: str, value) -> dict:
        return self.attributes[name].encode(value)

    def to_item(self, model: M) -> dict:
        return self.key_of(model) | _encode_attributes(self.attributes, model)

    def from_item(self, item: dict) -> M:
        return self.model.model_validate(_decode_attributes(self.attributes, self.model, item))
