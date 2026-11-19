from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RecipeSnapshotIngredient(BaseModel):
    ingredient_uuid: UUID
    name: str
    quantity: float = Field(..., ge=0)
    unit: str
    season_months: list[int] = Field(default_factory=list)
    green_score: int | None = Field(None, ge=0, le=100)
    rayon: str | None = None
    group: str | None = None
    supplier_uuid: UUID | None = None

    @field_validator("season_months", mode="before")
    @classmethod
    def check_months(cls, value: object) -> list[int]:
        if value is None:
            return []
        if isinstance(value, dict):
            months = [int(month) for month, score in value.items() if int(score) > 0]
        else:
            months = [int(month) for month in value]  # type: ignore[union-attr]
        if any(month < 1 or month > 12 for month in months):
            raise ValueError("season_months must contain values in [1..12]")
        return sorted(set(months))


class RecipeSnapshot(BaseModel):
    recipe_uuid: UUID
    title: str
    short_description: str | None = Field(None, max_length=200)
    servings_default: int = Field(..., ge=1)
    total_duration_min: int | None = Field(None, ge=0)
    ingredients: list[RecipeSnapshotIngredient] = Field(default_factory=list)
    snapshot_taken_at: datetime
    recipe_version: int | None = Field(None, ge=1)
