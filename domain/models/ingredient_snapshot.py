from uuid import UUID

from pydantic import BaseModel


class IngredientSnapshot(BaseModel):
    ingredient_uuid: UUID
    name: str
    unit: str | None = None
