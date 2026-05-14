import pytest
from datetime import datetime, timezone

from adapters.input.schemas.meal_plan_schema import (
    MealPlanCreateSchema,
    MealPlanPatchSchema,
    MealPlanSchema,
    MealPlanTransitionSchema,
    MealPlanUpdateSchema,
    SlotPatchOperationSchema,
)
from tests.units.factories import DEFAULT_DATE_END, DEFAULT_DATE_START, meal_plan


# --- MealPlanCreateSchema ---

def test_create_schema_valid():
    s = MealPlanCreateSchema(name="Farine", date_start=DEFAULT_DATE_START, date_end=DEFAULT_DATE_END)
    assert s.name == "Farine"
    assert s.status == "draft"


def test_create_schema_empty_name_raises():
    with pytest.raises(Exception):
        MealPlanCreateSchema(name="", date_start=DEFAULT_DATE_START, date_end=DEFAULT_DATE_END)


# --- MealPlanPatchSchema ---

def test_patch_schema_all_none():
    s = MealPlanPatchSchema()
    assert s.operations == []


def test_patch_schema_partial():
    s = MealPlanPatchSchema(
        operations=[
            SlotPatchOperationSchema(
                op="set_headcount",
                slot_date=DEFAULT_DATE_START,
                slot_code="lunch",
                headcount=2,
            )
        ]
    )
    assert s.operations[0].headcount == 2


def test_patch_schema_accepts_custom_slot_code():
    s = MealPlanPatchSchema(
        operations=[
            SlotPatchOperationSchema(
                op="set_headcount",
                slot_date=DEFAULT_DATE_START,
                slot_code="  goûter  ",
                headcount=2,
            )
        ]
    )
    assert s.operations[0].slot_code == "goûter"


def test_patch_schema_item_headcount():
    member_id = "01951234-5678-7abc-def0-000000000001"
    s = MealPlanPatchSchema(
        operations=[
            SlotPatchOperationSchema(
                op="add_item",
                slot_date=DEFAULT_DATE_START,
                slot_code="lunch",
                item={
                    "item_type": "ingredient",
                    "ingredient_uuid": "01951234-5678-7abc-def0-000000000000",
                    "ingredient_quantity": 1,
                    "ingredient_unit": "x",
                    "headcount": 3,
                    "member_ids": [member_id],
                },
            )
        ]
    )
    assert s.operations[0].item is not None
    assert s.operations[0].item.headcount == 3
    assert [str(member_uuid) for member_uuid in s.operations[0].item.member_ids] == [member_id]


def test_patch_schema_empty_name_raises():
    with pytest.raises(Exception):
        SlotPatchOperationSchema(op="set_headcount", slot_date=DEFAULT_DATE_START, slot_code="lunch", headcount=-1)


# --- MealPlanUpdateSchema ---

def test_update_schema_valid():
    s = MealPlanUpdateSchema(
        name="Sel fin",
        date_start=DEFAULT_DATE_START,
        date_end=DEFAULT_DATE_END,
        status="draft",
        slots=[],
    )
    assert s.name == "Sel fin"


def test_update_schema_empty_name_raises():
    with pytest.raises(Exception):
        MealPlanUpdateSchema(
            name="",
            date_start=DEFAULT_DATE_START,
            date_end=DEFAULT_DATE_END,
            status="draft",
            slots=[],
        )


# --- MealPlanSchema (response) ---

def test_meal_plan_schema_from_entity():
    entity = meal_plan(name="Farine")
    schema = MealPlanSchema.model_validate(entity)
    assert schema.name == "Farine"
    assert schema.is_deleted is False
    assert schema.version == 1


def test_meal_plan_schema_deleted_entity():
    entity = meal_plan(name="Sel", deleted_at=datetime.now(timezone.utc))
    schema = MealPlanSchema.model_validate(entity)
    assert schema.is_deleted is True


def test_meal_plan_schema_uuid_serialized():
    entity = meal_plan(name="Farine")
    schema = MealPlanSchema.model_validate(entity)
    assert str(schema.uuid) == str(entity.uuid)


def test_transition_schema_valid():
    schema = MealPlanTransitionSchema(target_status="confirmed")
    assert schema.target_status == "confirmed"
