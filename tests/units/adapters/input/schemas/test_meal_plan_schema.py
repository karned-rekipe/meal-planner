import pytest
from datetime import datetime, timezone

from adapters.input.schemas.meal_plan_schema import (
    MealPlanCreateSchema,
    MealPlanPatchSchema,
    MealPlanSchema,
    MealPlanUpdateSchema,
)
from domain.models.meal_plan import MealPlan


# --- MealPlanCreateSchema ---

def test_create_schema_valid():
    s = MealPlanCreateSchema(name="Farine")
    assert s.name == "Farine"


def test_create_schema_empty_name_raises():
    with pytest.raises(Exception):
        MealPlanCreateSchema(name="")


# --- MealPlanPatchSchema ---

def test_patch_schema_all_none():
    s = MealPlanPatchSchema()
    assert s.name is None


def test_patch_schema_partial():
    s = MealPlanPatchSchema(name="Farine complète")
    assert s.name == "Farine complète"


def test_patch_schema_empty_name_raises():
    with pytest.raises(Exception):
        MealPlanPatchSchema(name="")


# --- MealPlanUpdateSchema ---

def test_update_schema_valid():
    s = MealPlanUpdateSchema(name="Sel fin")
    assert s.name == "Sel fin"


def test_update_schema_empty_name_raises():
    with pytest.raises(Exception):
        MealPlanUpdateSchema(name="")


# --- MealPlanSchema (response) ---

def test_meal_plan_schema_from_entity():
    entity = MealPlan(name="Farine")
    schema = MealPlanSchema.model_validate(entity)
    assert schema.name == "Farine"
    assert schema.is_deleted is False
    assert schema.version == 1


def test_meal_plan_schema_deleted_entity():
    entity = MealPlan(name="Sel", deleted_at=datetime.now(timezone.utc))
    schema = MealPlanSchema.model_validate(entity)
    assert schema.is_deleted is True


def test_meal_plan_schema_uuid_serialized():
    entity = MealPlan(name="Farine")
    schema = MealPlanSchema.model_validate(entity)
    assert str(schema.uuid) == str(entity.uuid)

