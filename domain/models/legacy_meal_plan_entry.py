from datetime import date
from uuid import UUID

from pydantic import BaseModel

from domain.models.enums import MealItemType


class LegacyMealPlanEntry(BaseModel):
    uuid: UUID
    legacy_id: int
    date: date
    headcount: int | None = None
    entry_type: MealItemType
    recipe_uuid: UUID | None = None
    recipe_title: str | None = None
    ingredient_uuid: UUID | None = None
    ingredient_name: str | None = None
    note: str | None = None
    meal_slot_code_legacy: str | None = None
    legacy_rank: str | None = None
    status: str = "active"
