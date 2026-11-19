from datetime import datetime, timezone

import pytest
from uuid6 import uuid7

from domain.models.enums import MealPlanStatus
from tests.units.factories import meal_plan


async def test_create_and_read(repo):
    i = meal_plan(name="Farine")
    await repo.create(i)
    found = await repo.read(i.uuid)
    assert found is not None
    assert found.name == "Farine"


async def test_read_unknown_returns_none(repo):
    assert await repo.read(uuid7()) is None


async def test_find_by_name_match(repo):
    await repo.create(meal_plan(name="Farine de blé"))
    await repo.create(meal_plan(name="Sel fin"))
    result = await repo.find_by_name("farine")
    assert len(result) == 1
    assert result[0].name == "Farine de blé"


async def test_find_by_name_case_insensitive(repo):
    await repo.create(meal_plan(name="Farine"))
    assert len(await repo.find_by_name("FARINE")) == 1


async def test_find_by_name_excludes_deleted(repo):
    deleted = meal_plan(name="Farine", deleted_at=datetime.now(timezone.utc))
    await repo.create(deleted)
    result = await repo.find_by_name("farine")
    assert len(result) == 0


async def test_find_by_name_empty(repo):
    assert await repo.find_by_name("inconnu") == []


async def test_find_all_excludes_deleted(repo):
    await repo.create(meal_plan(name="Farine"))
    deleted = meal_plan(name="Sel", deleted_at=datetime.now(timezone.utc))
    await repo.create(deleted)
    result = await repo.find_all()
    assert len(result) == 1
    assert result[0].name == "Farine"


async def test_duplicate(repo):
    i = await repo.create(meal_plan(name="Farine"))
    clone = await repo.duplicate(i.uuid)
    assert clone.uuid != i.uuid
    assert clone.name == "Farine"


async def test_duplicate_deleted_raises(repo):
    i = meal_plan(name="Farine", deleted_at=datetime.now(timezone.utc))
    await repo.create(i)
    with pytest.raises(KeyError):
        await repo.duplicate(i.uuid)


async def test_find_page_by_name(repo):
    await repo.create(meal_plan(name="Farine de blé"))
    await repo.create(meal_plan(name="Farine de maïs"))
    await repo.create(meal_plan(name="Sel fin"))

    page, total = await repo.find_page_by_name("farine", offset=1, limit=1)

    assert total == 2
    assert len(page) == 1


async def test_find_page_filtered(repo):
    await repo.create(meal_plan(name="Semaine draft", status=MealPlanStatus.DRAFT))
    await repo.create(meal_plan(name="Semaine done", status=MealPlanStatus.DONE))

    page, total = await repo.find_page_filtered(status=MealPlanStatus.DONE, offset=0, limit=10)

    assert total == 1
    assert page[0].name == "Semaine done"


async def test_find_overlapping_confirmed(repo):
    confirmed = await repo.create(meal_plan(name="Confirmé", status=MealPlanStatus.CONFIRMED))
    await repo.create(meal_plan(name="Brouillon", status=MealPlanStatus.DRAFT))

    overlaps = await repo.find_overlapping_confirmed(confirmed.date_start, confirmed.date_end)
    excluded = await repo.find_overlapping_confirmed(confirmed.date_start, confirmed.date_end, exclude_uuid=confirmed.uuid)

    assert [plan.uuid for plan in overlaps] == [confirmed.uuid]
    assert excluded == []


async def test_upsert_by_legacy_id_updates_existing(repo):
    existing = await repo.upsert_by_legacy_id(
        42,
        meal_plan(name="Legacy", migration_metadata={"legacy_anchor_id": 42}),
    )

    updated = await repo.upsert_by_legacy_id(
        42,
        meal_plan(name="Legacy modifié", migration_metadata={"legacy_anchor_id": 42}),
    )

    assert updated.uuid == existing.uuid
    assert updated.name == "Legacy modifié"
    assert updated.version == 2
