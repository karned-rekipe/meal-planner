from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from arclith.domain.models.entity import Entity


class MealSlotDefinition(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=80)
    position: int = Field(..., ge=0)

    @field_validator("code", "label", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("meal slot code and label cannot be empty")
        return stripped


def default_meal_slots() -> list[MealSlotDefinition]:
    return [
        MealSlotDefinition(code="lunch", label="Déjeuner", position=0),
        MealSlotDefinition(code="dinner", label="Dîner", position=1),
    ]


class TenantPreferenceExclusions(BaseModel):
    ingredients: list[UUID] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


class TenantPreferenceFavorites(BaseModel):
    recipes: list[UUID] = Field(default_factory=list)


class TenantPreferences(Entity):
    exclusions: TenantPreferenceExclusions = Field(default_factory=TenantPreferenceExclusions)
    favorites: TenantPreferenceFavorites = Field(default_factory=TenantPreferenceFavorites)
    meal_slots: list[MealSlotDefinition] = Field(default_factory=default_meal_slots)

    @model_validator(mode="after")
    def meal_slots_must_be_unique(self) -> "TenantPreferences":
        codes = [slot.code for slot in self.meal_slots]
        if not codes:
            raise ValueError("tenant preferences require at least one meal slot")
        normalized_codes = [code.casefold() for code in codes]
        if len(normalized_codes) != len(set(normalized_codes)):
            raise ValueError("meal slot codes must be unique")
        return self
