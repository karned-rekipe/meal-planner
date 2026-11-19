from datetime import date
from uuid import UUID as StdUUID

from arclith.adapters.output.memory.repository import InMemoryRepository
from domain.models.enums import MealItemType, MealPlanStatus
from domain.models.legacy_meal_plan_entry import LegacyMealPlanEntry
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository


class InMemoryMealPlanRepository(InMemoryRepository[MealPlan], MealPlanRepository):
    async def find_by_name(self, name: str) -> list[MealPlan]:
        return [i for i in self._store.values() if name.lower() in i.name.lower() and not i.is_deleted]

    async def find_page_by_name(self, name: str, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        filtered = [i for i in self._store.values() if name.lower() in i.name.lower() and not i.is_deleted]
        total = len(filtered)
        page = filtered[offset: offset + limit] if limit is not None else filtered[offset:]
        return page, total

    async def find_page_filtered(
        self,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        filtered = [
            plan
            for plan in self._store.values()
            if self._matches_filters(plan, status=status, date_from=date_from, date_to=date_to)
        ]
        filtered.sort(key=lambda plan: (plan.date_start, plan.created_at), reverse=True)
        total = len(filtered)
        page = filtered[offset: offset + limit] if limit is not None else filtered[offset:]
        return page, total

    async def find_overlapping_confirmed(
        self,
        date_start: date,
        date_end: date,
        exclude_uuid: StdUUID | None = None,
    ) -> list[MealPlan]:
        return [
            plan
            for plan in self._store.values()
            if not plan.is_deleted
            and plan.status == MealPlanStatus.CONFIRMED
            and plan.date_start <= date_end
            and plan.date_end >= date_start
            and (exclude_uuid is None or str(plan.uuid) != str(exclude_uuid))
        ]

    async def find_recent_recipe_uuids(
        self,
        since: date,
        statuses: tuple[MealPlanStatus, ...] = (MealPlanStatus.CONFIRMED, MealPlanStatus.DONE),
    ) -> set[StdUUID]:
        recipe_uuids: set[StdUUID] = set()
        for plan in self._store.values():
            if plan.is_deleted or plan.status not in statuses or plan.date_end < since:
                continue
            for slot in plan.slots:
                for item in slot.items:
                    if item.item_type == MealItemType.RECIPE and item.recipe_uuid is not None:
                        recipe_uuids.add(item.recipe_uuid)
        return recipe_uuids

    async def find_legacy_entries(self, date_start: date, date_end: date) -> list[LegacyMealPlanEntry]:
        return []

    async def upsert_by_legacy_id(self, legacy_id_value: int, plan: MealPlan) -> MealPlan:
        for existing in self._store.values():
            metadata = existing.migration_metadata or {}
            if metadata.get("legacy_anchor_id") == legacy_id_value:
                updated = plan.model_copy(update={"uuid": existing.uuid, "version": existing.version + 1})
                self._store[updated.uuid] = updated
                return updated
        self._store[plan.uuid] = plan
        return plan

    @staticmethod
    def _matches_filters(
        plan: MealPlan,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> bool:
        if plan.is_deleted:
            return False
        if status is not None and plan.status != status:
            return False
        if date_from is not None and plan.date_end < date_from:
            return False
        return date_to is None or plan.date_start <= date_to
