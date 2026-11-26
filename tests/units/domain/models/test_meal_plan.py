import pytest
from domain.models.meal_slot import MealSlot
from domain.models.recipe_snapshot import RecipeSnapshotIngredient
from tests.units.factories import DEFAULT_DATE_START, meal_plan
from uuid6 import uuid7


def test_valid_meal_plan():
    i = meal_plan(name="Farine")
    assert i.name == "Farine"


def test_name_stripped():
    i = meal_plan(name="  Sel fin  ")
    assert i.name == "Sel fin"


def test_empty_name_raises():
    with pytest.raises(Exception):
        meal_plan(name="")


def test_blank_name_raises():
    with pytest.raises(Exception):
        meal_plan(name="   ")



def test_inherits_entity_fields():
    from uuid6 import UUID
    i = meal_plan(name="Sel")
    assert isinstance(i.uuid, UUID)
    assert i.version == 1
    assert not i.is_deleted


def test_model_copy_update():
    i = meal_plan(name="Farine")
    copy = i.model_copy(update={"name": "Farine complète"})
    assert copy.name == "Farine complète"
    assert copy.uuid == i.uuid


def test_with_complete_empty_slots_preserves_custom_meals():
    plan = meal_plan(slots=[MealSlot(date=DEFAULT_DATE_START, slot_code="goûter", headcount=2)])

    completed = plan.with_complete_empty_slots()
    first_day_slots = [slot for slot in completed.slots if slot.date == DEFAULT_DATE_START]

    assert [slot.slot_code for slot in first_day_slots] == ["lunch", "dinner", "goûter"]
    assert first_day_slots[2].headcount == 2
    assert len(completed.slots) == 15


def test_meal_slot_headcount_allows_zero():
    slot = MealSlot(date=DEFAULT_DATE_START, slot_code="lunch", headcount=0)
    assert slot.headcount == 0


def test_meal_slot_headcount_rejects_more_than_twenty():
    with pytest.raises(Exception):
        MealSlot(date=DEFAULT_DATE_START, slot_code="lunch", headcount=21)


def test_recipe_snapshot_ingredient_rejects_non_collection_season_months():
    with pytest.raises(ValueError, match="collection of months"):
        RecipeSnapshotIngredient(
            ingredient_uuid=uuid7(),
            name="Carotte",
            quantity=1,
            unit="pièce",
            season_months=3,
        )
