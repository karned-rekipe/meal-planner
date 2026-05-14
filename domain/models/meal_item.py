from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from domain.models.enums import MealItemType
from domain.models.recipe_snapshot import RecipeSnapshot


class MealItem(BaseModel):
    uuid: UUID = Field(default_factory=uuid4)
    position: int = Field(..., ge=0)
    item_type: MealItemType
    headcount: int | None = Field(None, ge=1, le=99)
    member_ids: list[UUID] = Field(default_factory=list)

    recipe_uuid: UUID | None = None
    recipe_snapshot: RecipeSnapshot | None = None
    recipe_status: str | None = None
    recipe_modified: bool = False

    ingredient_uuid: UUID | None = None
    ingredient_name: str | None = None
    ingredient_quantity: float | None = Field(None, ge=0)
    ingredient_unit: str | None = None

    note: str | None = Field(None, max_length=500)
    legacy_id: int | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> "MealItem":
        if self.item_type == MealItemType.RECIPE:
            if self.recipe_uuid is None or self.recipe_snapshot is None:
                raise ValueError("recipe item requires recipe_uuid and recipe_snapshot")
        elif self.item_type == MealItemType.INGREDIENT:
            if self.ingredient_uuid is None or self.ingredient_quantity is None or not self.ingredient_unit:
                raise ValueError("ingredient item requires ingredient_uuid, quantity and unit")
        elif self.item_type in (MealItemType.NOTE, MealItemType.PREP_TASK):
            if not self.note:
                raise ValueError(f"{self.item_type.value} item requires note")
        elif self.item_type == MealItemType.MIXED and not self.note:
            raise ValueError("mixed legacy item requires note")
        return self
