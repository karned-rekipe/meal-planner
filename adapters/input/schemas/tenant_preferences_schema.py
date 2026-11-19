from uuid import UUID as StdUUID

from pydantic import BaseModel, ConfigDict, Field

from arclith.adapters.input.schemas.base_schema import BaseSchema
from domain.models.tenant_preferences import (
    MealSlotDefinition,
    TenantPreferenceExclusions,
    TenantPreferenceFavorites,
    TenantPreferences,
)


class TenantPreferenceExclusionsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ingredients: list[StdUUID] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


class TenantPreferenceFavoritesSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipes: list[StdUUID] = Field(default_factory=list)


class MealSlotDefinitionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=80)
    position: int = Field(..., ge=0)


def default_meal_slot_schemas() -> list[MealSlotDefinitionSchema]:
    return [
        MealSlotDefinitionSchema(code="lunch", label="Déjeuner", position=0),
        MealSlotDefinitionSchema(code="dinner", label="Dîner", position=1),
    ]


class TenantPreferencesUpdateSchema(BaseModel):
    exclusions: TenantPreferenceExclusionsSchema = Field(default_factory=TenantPreferenceExclusionsSchema)
    favorites: TenantPreferenceFavoritesSchema = Field(default_factory=TenantPreferenceFavoritesSchema)
    meal_slots: list[MealSlotDefinitionSchema] = Field(default_factory=default_meal_slot_schemas)


class TenantPreferencesSchema(BaseSchema):
    exclusions: TenantPreferenceExclusionsSchema = Field(default_factory=TenantPreferenceExclusionsSchema)
    favorites: TenantPreferenceFavoritesSchema = Field(default_factory=TenantPreferenceFavoritesSchema)
    meal_slots: list[MealSlotDefinitionSchema] = Field(default_factory=default_meal_slot_schemas)


def tenant_preferences_update_payload_to_domain(payload: TenantPreferencesUpdateSchema) -> TenantPreferences:
    return TenantPreferences(
        exclusions=TenantPreferenceExclusions.model_validate(payload.exclusions.model_dump()),
        favorites=TenantPreferenceFavorites.model_validate(payload.favorites.model_dump()),
        meal_slots=[
            MealSlotDefinition.model_validate(slot.model_dump())
            for slot in sorted(payload.meal_slots, key=lambda item: item.position)
        ],
    )
