import pytest
from domain.models.meal_plan import MealPlan


def test_valid_meal_plan():
    i = MealPlan(name="Farine")
    assert i.name == "Farine"


def test_name_stripped():
    i = MealPlan(name="  Sel fin  ")
    assert i.name == "Sel fin"


def test_empty_name_raises():
    with pytest.raises(Exception):
        MealPlan(name="")


def test_blank_name_raises():
    with pytest.raises(Exception):
        MealPlan(name="   ")



def test_inherits_entity_fields():
    from uuid6 import UUID
    i = MealPlan(name="Sel")
    assert isinstance(i.uuid, UUID)
    assert i.version == 1
    assert not i.is_deleted


def test_model_copy_update():
    i = MealPlan(name="Farine")
    copy = i.model_copy(update={"name": "Farine complète"})
    assert copy.name == "Farine complète"
    assert copy.uuid == i.uuid

