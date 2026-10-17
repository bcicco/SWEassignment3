from decimal import Decimal
from enum import Enum

from pydantic import Field

from shared.base import DataHolder


class ParcelSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


# only the details needed for pricing and handling (S5)
class Parcel(DataHolder):
    size: ParcelSize
    weight_kg: Decimal = Field(gt = 0)
    quantity: int = Field(default = 1, ge = 1)
