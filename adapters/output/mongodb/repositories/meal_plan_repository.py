import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, cast
from uuid import UUID as StdUUID

from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from uuid6 import uuid7

from domain.models.enums import MealItemType, MealPlanStatus
from domain.models.legacy_meal_plan_entry import LegacyMealPlanEntry
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository

MEAL_PLAN_DOCUMENT_TYPE = "meal_plan"
LEGACY_ENTRY_DOCUMENT_TYPE = "legacy_entry"


class MongoDBMealPlanRepository(MongoDBRepository[MealPlan], MealPlanRepository):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        super().__init__(config, MealPlan, logger)

    def _to_doc(self, entity: MealPlan) -> dict[str, Any]:
        doc = entity.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        doc["document_type"] = MEAL_PLAN_DOCUMENT_TYPE
        return doc

    async def read(self, uuid: StdUUID) -> MealPlan | None:
        async with self._collection() as col:
            doc = await col.find_one(self._meal_plan_match({"_id": str(uuid)}))
        return self._from_doc(doc) if doc else None

    async def update(self, entity: MealPlan) -> MealPlan:
        async with self._collection() as col:
            await col.replace_one(self._meal_plan_match({"_id": str(entity.uuid)}), self._to_doc(entity))
        return entity

    async def delete(self, uuid: StdUUID) -> None:
        async with self._collection() as col:
            await col.delete_one(self._meal_plan_match({"_id": str(uuid)}))

    async def find_all(self) -> list[MealPlan]:
        async with self._collection() as col:
            return [self._from_doc(doc) async for doc in col.find(self._meal_plan_match({"deleted_at": None}))]

    async def find_page(self, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        return await self._find_page_by_match(self._meal_plan_match({"deleted_at": None}), offset, limit)

    async def find_deleted(self) -> list[MealPlan]:
        async with self._collection() as col:
            return [
                self._from_doc(doc)
                async for doc in col.find(self._meal_plan_match({"deleted_at": {"$ne": None, "$exists": True}}))
            ]

    async def duplicate(self, uuid: StdUUID) -> MealPlan:
        existing = await self.read(uuid)
        if existing is None:
            raise KeyError(f"Entity with uuid {uuid} not found")
        clone = existing.model_copy(update={"uuid": uuid7()})
        return await self.create(clone)

    async def find_by_name(self, name: str) -> list[MealPlan]:
        async with self._collection() as col:
            escaped_name = re.escape(name)
            return [
                self._from_doc(doc)
                async for doc in col.find(
                    self._meal_plan_match({"name": {"$regex": escaped_name, "$options": "i"}, "deleted_at": None})
                )
            ]

    async def find_page_by_name(self, name: str, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        """Single-query pagination with name filter via $facet."""
        escaped_name = re.escape(name)
        return await self._find_page_by_match(
            self._meal_plan_match({"name": {"$regex": escaped_name, "$options": "i"}, "deleted_at": None}),
            offset,
            limit,
        )

    async def find_page_filtered(
        self,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        match: dict[str, Any] = {"deleted_at": None}
        if status is not None:
            match["status"] = status.value
        if date_from is not None:
            match["date_end"] = {"$gte": date_from.isoformat()}
        if date_to is not None:
            match["date_start"] = {"$lte": date_to.isoformat()}
        return await self._find_page_by_match(self._meal_plan_match(match), offset, limit)

    async def find_overlapping_confirmed(
        self,
        date_start: date,
        date_end: date,
        exclude_uuid: StdUUID | None = None,
    ) -> list[MealPlan]:
        match: dict[str, Any] = {
            "deleted_at": None,
            "status": MealPlanStatus.CONFIRMED.value,
            "date_start": {"$lte": date_end.isoformat()},
            "date_end": {"$gte": date_start.isoformat()},
        }
        if exclude_uuid is not None:
            match["_id"] = {"$ne": str(exclude_uuid)}
        async with self._collection() as col:
            return [self._from_doc(doc) async for doc in col.find(self._meal_plan_match(match))]

    async def find_recent_recipe_uuids(
        self,
        since: date,
        statuses: tuple[MealPlanStatus, ...] = (MealPlanStatus.CONFIRMED, MealPlanStatus.DONE),
    ) -> set[StdUUID]:
        match = {
            "deleted_at": None,
            "status": {"$in": [status.value for status in statuses]},
            "date_end": {"$gte": since.isoformat()},
        }
        async with self._collection() as col:
            plans = [self._from_doc(doc) async for doc in col.find(self._meal_plan_match(match))]
        recipe_uuids: set[StdUUID] = set()
        for plan in plans:
            for slot in plan.slots:
                for item in slot.items:
                    if item.item_type == MealItemType.RECIPE and item.recipe_uuid is not None:
                        recipe_uuids.add(item.recipe_uuid)
        return recipe_uuids

    async def find_legacy_entries(self, date_start: date, date_end: date) -> list[LegacyMealPlanEntry]:
        match = self._legacy_entry_match({
            "date": {"$gte": date_start.isoformat(), "$lte": date_end.isoformat()},
            "status": "active",
        })
        async with self._collection() as col:
            docs = await col.find(match).sort([
                ("date", 1),
                ("meal_slot_code_legacy", 1),
                ("legacy_rank", 1),
                ("legacy_id", 1),
            ]).to_list(length=None)
            recipes_by_uuid = await self._lookup_names(col.database["recipe"], docs, "recipe_uuid")
            ingredients_by_uuid = await self._lookup_names(col.database["ingredient"], docs, "ingredient_uuid")

        entries: list[LegacyMealPlanEntry] = []
        for doc in docs:
            try:
                entries.append(self._legacy_entry_from_doc(doc, recipes_by_uuid, ingredients_by_uuid))
            except (TypeError, ValueError) as exc:
                self._logger.warning(f"Skipping invalid legacy meal plan entry {doc.get('_id')}: {exc}")
        return entries

    async def upsert_by_legacy_id(self, legacy_id_value: int, plan: MealPlan) -> MealPlan:
        async with self._collection() as col:
            existing = await col.find_one(self._meal_plan_match({"migration_metadata.legacy_anchor_id": legacy_id_value}))
            if existing is not None:
                current = self._from_doc(existing)
                plan = plan.model_copy(update={"uuid": current.uuid, "version": current.version + 1})
                await col.replace_one(self._meal_plan_match({"_id": str(current.uuid)}), self._to_doc(plan))
                return plan
            await col.insert_one(self._to_doc(plan))
        return plan

    async def _find_page_by_match(
        self,
        match: dict[str, Any],
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        data_pipeline: list[dict] = [{"$skip": offset}]
        if limit is not None:
            data_pipeline.append({"$limit": limit})
        pipeline: Sequence[Mapping[str, Any]] = cast(
            Sequence[Mapping[str, Any]],
            [
                {"$match": match},
                {"$sort": {"date_start": -1, "created_at": -1}},
                {"$facet": {
                    "data": data_pipeline,
                    "total": [{"$count": "count"}],
                }},
            ]
        )
        async with self._collection() as col:
            result = await col.aggregate(pipeline).to_list(length=1)
        if not result:
            return [], 0
        facet = result[0]
        items = [self._from_doc(doc) for doc in facet.get("data", [])]
        total = facet["total"][0]["count"] if facet.get("total") else 0
        return items, total

    @staticmethod
    def _meal_plan_match(match: dict[str, Any] | None = None) -> dict[str, Any]:
        base = {
            "$or": [
                {"document_type": MEAL_PLAN_DOCUMENT_TYPE},
                {
                    "document_type": {"$exists": False},
                    "name": {"$exists": True},
                    "slots": {"$exists": True},
                },
            ],
        }
        if match is None:
            return base
        return {"$and": [base, match]}

    @staticmethod
    def _legacy_entry_match(match: dict[str, Any]) -> dict[str, Any]:
        base = {
            "$or": [
                {"document_type": LEGACY_ENTRY_DOCUMENT_TYPE},
                {
                    "document_type": {"$exists": False},
                    "legacy_id": {"$exists": True},
                    "entry_type": {"$exists": True},
                },
            ],
        }
        return {"$and": [base, match]}

    @staticmethod
    async def _lookup_names(collection: Any, docs: list[dict[str, Any]], field_name: str) -> dict[str, str]:
        uuids = sorted({str(doc[field_name]) for doc in docs if doc.get(field_name)})
        if not uuids:
            return {}
        cursor = collection.find({"_id": {"$in": uuids}}, {"name": 1})
        return {str(doc["_id"]): str(doc.get("name") or "") for doc in await cursor.to_list(length=None)}

    @classmethod
    def _legacy_entry_from_doc(
        cls,
        doc: dict[str, Any],
        recipes_by_uuid: dict[str, str],
        ingredients_by_uuid: dict[str, str],
    ) -> LegacyMealPlanEntry:
        recipe_uuid = cls._optional_uuid(doc.get("recipe_uuid"))
        ingredient_uuid = cls._optional_uuid(doc.get("ingredient_uuid"))
        return LegacyMealPlanEntry(
            uuid=StdUUID(str(doc["_id"])),
            legacy_id=int(doc["legacy_id"]),
            date=cls._date_from_value(doc["date"]),
            headcount=cls._positive_int_or_none(doc.get("headcount")),
            entry_type=cls._entry_type_from_value(doc.get("entry_type")),
            recipe_uuid=recipe_uuid,
            recipe_title=recipes_by_uuid.get(str(recipe_uuid)) if recipe_uuid is not None else None,
            ingredient_uuid=ingredient_uuid,
            ingredient_name=ingredients_by_uuid.get(str(ingredient_uuid)) if ingredient_uuid is not None else None,
            note=doc.get("note"),
            meal_slot_code_legacy=doc.get("meal_slot_code_legacy"),
            legacy_rank=doc.get("legacy_rank"),
            status=str(doc.get("status") or "active"),
        )

    @staticmethod
    def _date_from_value(value: Any) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @staticmethod
    def _optional_uuid(value: Any) -> StdUUID | None:
        if value in (None, ""):
            return None
        return StdUUID(str(value))

    @staticmethod
    def _positive_int_or_none(value: Any) -> int | None:
        if value in (None, ""):
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None

    @staticmethod
    def _entry_type_from_value(value: Any) -> MealItemType:
        try:
            return MealItemType(str(value))
        except ValueError:
            return MealItemType.MIXED
