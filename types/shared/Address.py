from pydantic import Field

from shared.base import DataHolder


class Address(DataHolder): 
    street: str = Field(min_length = 1)
    suburb: str = Field(min_length = 1)
    postcode: str = Field(pattern = r"^\d{4}$")
