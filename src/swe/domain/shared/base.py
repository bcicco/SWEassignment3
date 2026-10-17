from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from swe.domain.shared.ids import new_id, now


# data holders are never altered once created (§3.3)
class DataHolder(BaseModel):
    model_config = ConfigDict(frozen = True)


# a data holder stored as its own item, attributed to whoever created it
class Record(DataHolder):
    id: str = Field(default_factory = new_id)
    created_at: datetime = Field(default_factory = now)
    created_by: str | None = None # None for anonymous actions (A9)
