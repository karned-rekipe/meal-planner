from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from arclith.adapters.output.mongodb.config import MongoDBConfig
from uuid6 import uuid7

from adapters.output.mongodb.repositories.meal_plan_repository import MongoDBMealPlanRepository
from domain.models.enums import MealItemType, MealPlanStatus
from domain.models.meal_item import MealItem
from domain.models.meal_slot import MealSlot
from domain.models.recipe_snapshot import RecipeSnapshot
from tests.units.factories import meal_plan


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self.sort_spec = None

    def sort(self, spec):
        self.sort_spec = spec
        return self

    def __aiter__(self):
        self._iterator = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def to_list(self, length=None):
        return list(self.docs)


class FakeCollection:
    def __init__(self, docs=(), *, aggregate_results=(), find_one_results=None, database=None):
        self.docs = list(docs)
        self.aggregate_results = list(aggregate_results)
        self.find_one_results = list(find_one_results or [])
        self.database = database or {}
        self.calls = []

    async def find_one(self, query):
        self.calls.append(("find_one", query))
        if self.find_one_results:
            return self.find_one_results.pop(0)
        return self.docs[0] if self.docs else None

    async def replace_one(self, query, doc):
        self.calls.append(("replace_one", query, doc))

    async def delete_one(self, query):
        self.calls.append(("delete_one", query))

    async def insert_one(self, doc):
        self.calls.append(("insert_one", doc))

    def find(self, query, projection=None):
        self.calls.append(("find", query, projection))
        return FakeCursor(self.docs)

    def aggregate(self, pipeline):
        self.calls.append(("aggregate", pipeline))
        return FakeCursor(self.aggregate_results)


def _repository(logger):
    return MongoDBMealPlanRepository(
        MongoDBConfig(db_name="meal-planner-test", uri="mongodb://localhost:27017"),
        logger,
    )


def _attach_collection(monkeypatch, repository, collection):
    @asynccontextmanager
    async def collection_context():
        yield collection

    monkeypatch.setattr(repository, "_collection", collection_context)


def _recipe_plan():
    recipe_uuid = uuid7()
    snapshot = RecipeSnapshot(
        recipe_uuid=recipe_uuid,
        title="Soupe",
        servings_default=4,
        ingredients=[],
        snapshot_taken_at=datetime.now(timezone.utc),
        recipe_version=2,
    )
    item = MealItem(
        position=0,
        item_type=MealItemType.RECIPE,
        recipe_uuid=recipe_uuid,
        recipe_snapshot=snapshot,
    )
    return meal_plan(
        status=MealPlanStatus.CONFIRMED,
        slots=[MealSlot(date=date(2026, 1, 5), slot_code="lunch", items=[item])],
    ), recipe_uuid


async def test_mongodb_repository_crud_queries_and_filtered_reads(monkeypatch, logger):
    repository = _repository(logger)
    plan = meal_plan(name="Semaine Mongo")
    doc = repository._to_doc(plan)
    collection = FakeCollection([doc])
    _attach_collection(monkeypatch, repository, collection)

    assert repository._from_doc(doc).uuid == plan.uuid
    assert (await repository.read(plan.uuid)).name == "Semaine Mongo"
    await repository.update(plan)
    await repository.delete(plan.uuid)
    assert [item.uuid for item in await repository.find_all()] == [plan.uuid]
    assert [item.uuid for item in await repository.find_deleted()] == [plan.uuid]
    assert [item.uuid for item in await repository.find_by_name("Mongo.*")] == [plan.uuid]
    assert [item.uuid for item in await repository.find_overlapping_confirmed(
        plan.date_start,
        plan.date_end,
        exclude_uuid=plan.uuid,
    )] == [plan.uuid]

    assert any(call[0] == "replace_one" for call in collection.calls)
    assert any(call[0] == "delete_one" for call in collection.calls)
    find_queries = [call[1] for call in collection.calls if call[0] == "find"]
    assert any(
        query["$and"][1].get("name", {}).get("$regex") == r"Mongo\.\*"
        for query in find_queries
        if "$and" in query
    )


async def test_mongodb_repository_read_unknown_and_duplicate_paths(monkeypatch, logger):
    repository = _repository(logger)
    collection = FakeCollection()
    _attach_collection(monkeypatch, repository, collection)

    assert await repository.read(uuid7()) is None
    with pytest.raises(KeyError):
        await repository.duplicate(uuid7())

    existing = meal_plan(name="Source")

    async def read_existing(uuid):
        return existing

    async def create_clone(entity):
        return entity

    monkeypatch.setattr(repository, "read", read_existing)
    monkeypatch.setattr(repository, "create", create_clone)
    clone = await repository.duplicate(existing.uuid)
    assert clone.uuid != existing.uuid
    assert clone.name == existing.name


async def test_mongodb_repository_pagination_and_filters(monkeypatch, logger):
    repository = _repository(logger)
    plan = meal_plan(name="Page")
    doc = repository._to_doc(plan)
    collection = FakeCollection(aggregate_results=[{"data": [doc], "total": [{"count": 1}]}])
    _attach_collection(monkeypatch, repository, collection)

    page, total = await repository.find_page(offset=2, limit=5)
    assert [item.uuid for item in page] == [plan.uuid]
    assert total == 1

    await repository.find_page_by_name("Page+", offset=1, limit=None)
    await repository.find_page_filtered(
        status=MealPlanStatus.CONFIRMED,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        offset=0,
        limit=10,
    )
    pipelines = [call[1] for call in collection.calls if call[0] == "aggregate"]
    assert any({"$skip": 2} in pipeline[2]["$facet"]["data"] for pipeline in pipelines)
    assert any({"$limit": 5} in pipeline[2]["$facet"]["data"] for pipeline in pipelines)
    assert any("confirmed" in str(pipeline) for pipeline in pipelines)

    empty_collection = FakeCollection(aggregate_results=[])
    _attach_collection(monkeypatch, repository, empty_collection)
    assert await repository.find_page() == ([], 0)


async def test_mongodb_repository_finds_recent_recipe_uuids(monkeypatch, logger):
    repository = _repository(logger)
    plan, recipe_uuid = _recipe_plan()
    collection = FakeCollection([repository._to_doc(plan)])
    _attach_collection(monkeypatch, repository, collection)

    result = await repository.find_recent_recipe_uuids(
        date(2025, 12, 1),
        statuses=(MealPlanStatus.CONFIRMED,),
    )

    assert result == {UUID(str(recipe_uuid))}


async def test_mongodb_repository_reads_legacy_entries_and_skips_invalid_documents(monkeypatch, logger):
    repository = _repository(logger)
    recipe_uuid = uuid7()
    ingredient_uuid = uuid7()
    valid = {
        "_id": str(uuid7()),
        "legacy_id": 42,
        "date": "2026-01-05",
        "headcount": "4",
        "entry_type": "recipe",
        "recipe_uuid": str(recipe_uuid),
        "ingredient_uuid": str(ingredient_uuid),
        "note": None,
        "meal_slot_code_legacy": "1",
        "legacy_rank": "a",
        "status": "active",
    }
    invalid = {**valid, "_id": "invalid", "legacy_id": "not-an-int"}
    recipe_collection = FakeCollection([{"_id": str(recipe_uuid), "name": "Soupe"}])
    ingredient_collection = FakeCollection([{"_id": str(ingredient_uuid), "name": "Carotte"}])
    collection = FakeCollection(
        [valid, invalid],
        database={"recipe": recipe_collection, "ingredient": ingredient_collection},
    )
    _attach_collection(monkeypatch, repository, collection)

    entries = await repository.find_legacy_entries(date(2026, 1, 1), date(2026, 1, 31))

    assert len(entries) == 1
    assert entries[0].recipe_title == "Soupe"
    assert entries[0].ingredient_name == "Carotte"
    assert entries[0].headcount == 4
    assert logger.records[-1]["level"].value == "WARNING"


async def test_mongodb_repository_upserts_existing_or_new_legacy_plan(monkeypatch, logger):
    repository = _repository(logger)
    existing = meal_plan(name="Ancien", migration_metadata={"legacy_anchor_id": 42})
    collection = FakeCollection(find_one_results=[repository._to_doc(existing), None])
    _attach_collection(monkeypatch, repository, collection)

    updated = await repository.upsert_by_legacy_id(
        42,
        meal_plan(name="Mis à jour", migration_metadata={"legacy_anchor_id": 42}),
    )
    created = await repository.upsert_by_legacy_id(
        43,
        meal_plan(name="Nouveau", migration_metadata={"legacy_anchor_id": 43}),
    )

    assert updated.uuid == existing.uuid
    assert updated.version == existing.version + 1
    assert created.name == "Nouveau"
    assert any(call[0] == "replace_one" for call in collection.calls)
    assert any(call[0] == "insert_one" for call in collection.calls)


def test_mongodb_repository_document_match_and_legacy_conversions(logger):
    repository = _repository(logger)
    identifier = uuid7()

    assert repository._meal_plan_match()["$or"][0] == {"document_type": "meal_plan"}
    assert repository._legacy_entry_match({"status": "active"})["$and"][1] == {"status": "active"}
    assert repository._optional_uuid(None) is None
    assert repository._optional_uuid("") is None
    assert repository._optional_uuid(identifier) == UUID(str(identifier))
    assert repository._date_from_value(date(2026, 1, 5)) == date(2026, 1, 5)
    assert repository._date_from_value("2026-01-06") == date(2026, 1, 6)
    assert repository._positive_int_or_none(None) is None
    assert repository._positive_int_or_none("0") is None
    assert repository._positive_int_or_none("3") == 3
    assert repository._entry_type_from_value("note") == MealItemType.NOTE
    assert repository._entry_type_from_value("unknown") == MealItemType.MIXED


async def test_mongodb_repository_lookup_names_handles_empty_and_named_rows(logger):
    repository = _repository(logger)
    identifier = uuid7()
    collection = FakeCollection([{"_id": str(identifier), "name": "Soupe"}])

    assert await repository._lookup_names(collection, [], "recipe_uuid") == {}
    assert await repository._lookup_names(
        collection,
        [{"recipe_uuid": str(identifier)}, {"recipe_uuid": str(identifier)}],
        "recipe_uuid",
    ) == {str(identifier): "Soupe"}
