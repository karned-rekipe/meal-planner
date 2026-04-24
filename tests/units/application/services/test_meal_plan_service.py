import pytest
from uuid6 import uuid7

from application.services.meal_plan_service import MealPlanService
from domain.models.meal_plan import MealPlan


@pytest.fixture
def service(repo, logger):
    return MealPlanService(repo, logger)


async def test_create_and_read(service):
    meal_plan = await service.create(MealPlan(name="Farine"))
    found = await service.read(meal_plan.uuid)
    assert found is not None
    assert found.name == "Farine"


async def test_update(service):
    meal_plan = await service.create(MealPlan(name="Farine"))
    updated = await service.update(meal_plan.model_copy(update={"name": "Farine complète"}))
    assert updated.name == "Farine complète"
    assert updated.version == 2


async def test_delete_hides_from_read(service):
    meal_plan = await service.create(MealPlan(name="Sel"))
    await service.delete(meal_plan.uuid)
    assert await service.read(meal_plan.uuid) is None


async def test_find_all(service):
    await service.create(MealPlan(name="Farine"))
    await service.create(MealPlan(name="Sel"))
    result = await service.find_all()
    assert len(result) == 2


async def test_find_by_name(service):
    await service.create(MealPlan(name="Farine de blé"))
    await service.create(MealPlan(name="Sel fin"))
    result = await service.find_by_name("farine")
    assert len(result) == 1
    assert result[0].name == "Farine de blé"


async def test_duplicate(service):
    meal_plan = await service.create(MealPlan(name="Farine"))
    clone = await service.duplicate(meal_plan.uuid)
    assert clone.uuid != meal_plan.uuid
    assert clone.name == "Farine"


async def test_read_unknown_returns_none(service):
    assert await service.read(uuid7()) is None


async def test_find_by_name_no_results(service):
    await service.create(MealPlan(name="Sel"))
    result = await service.find_by_name("farine")
    assert result == []

