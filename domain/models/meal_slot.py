from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from domain.models.enums import HeadcountSource, SlotCode
from domain.models.meal_item import MealItem


class MealSlot(BaseModel):
    date: date
    slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    headcount: int | None = Field(None, ge=0, le=20)
    headcount_source: HeadcountSource | None = None
    member_ids: list[UUID] = Field(default_factory=list)
    items: list[MealItem] = Field(default_factory=list)

    @field_validator("slot_code", mode="before")
    @classmethod
    def strip_slot_code(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("slot_code cannot be empty")
        return stripped

    @model_validator(mode="after")
    def positions_must_be_unique_and_dense(self) -> "MealSlot":
        positions = [item.position for item in self.items]
        if positions and sorted(positions) != list(range(len(positions))):
            raise ValueError("MealItem positions must be a dense sequence starting at 0")
        return self
