from datetime import date
from uuid import UUID as StdUUID

from arclith.adapters.output.duckdb.repository import DuckDBRepository
from domain.models.enums import MealPlanStatus
from domain.models.legacy_meal_plan_entry import LegacyMealPlanEntry
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository


class DuckDBMealPlanRepository(DuckDBRepository[MealPlan], MealPlanRepository):
    def __init__(self, path: str) -> None:
        super().__init__(path, MealPlan)

    # noinspection SqlNoDataSourceInspection
    async def find_by_name(self, name: str) -> list[MealPlan]:
        rows = self._fetch(
            f"SELECT * FROM {self._table} WHERE deleted_at IS NULL AND lower(name) LIKE ?",  # nosec B608
            [f"%{name.lower()}%"],
        )
        return [self._row_to_entity(r) for r in rows]

    # noinspection SqlNoDataSourceInspection
    async def find_page_by_name(self, name: str, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        """Single-query pagination with name filter via window function."""
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        rows = self._fetch(
            f"SELECT *, COUNT(*) OVER () AS __total FROM {self._table} "  # nosec B608
            f"WHERE deleted_at IS NULL AND lower(name) LIKE ? "
            f"ORDER BY rowid OFFSET {offset} {limit_clause}",
            [f"%{name.lower()}%"],
        )
        total = int(rows[0]["__total"]) if rows else 0
        return [self._row_to_entity({k: v for k, v in r.items() if k != "__total"}) for r in rows], total

    async def find_page_filtered(
        self,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        items, total = await self.find_page(offset, limit)
        filtered = [
            plan
            for plan in items
            if (status is None or plan.status == status)
            and (date_from is None or plan.date_end >= date_from)
            and (date_to is None or plan.date_start <= date_to)
        ]
        return filtered, total

    async def find_overlapping_confirmed(
        self,
        date_start: date,
        date_end: date,
        exclude_uuid: StdUUID | None = None,
    ) -> list[MealPlan]:
        items = await self.find_all()
        return [
            plan
            for plan in items
            if plan.status == MealPlanStatus.CONFIRMED
            and plan.date_start <= date_end
            and plan.date_end >= date_start
            and (exclude_uuid is None or str(plan.uuid) != str(exclude_uuid))
        ]

    async def find_recent_recipe_uuids(
        self,
        since: date,
        statuses: tuple[MealPlanStatus, ...] = (MealPlanStatus.CONFIRMED, MealPlanStatus.DONE),
    ) -> set[StdUUID]:
        items = await self.find_all()
        recipe_uuids: set[StdUUID] = set()
        for plan in items:
            if plan.status not in statuses or plan.date_end < since:
                continue
            for slot in plan.slots:
                for item in slot.items:
                    if item.recipe_uuid is not None:
                        recipe_uuids.add(item.recipe_uuid)
        return recipe_uuids

    async def find_legacy_entries(self, date_start: date, date_end: date) -> list[LegacyMealPlanEntry]:
        return []

    async def upsert_by_legacy_id(self, legacy_id_value: int, plan: MealPlan) -> MealPlan:
        items = await self.find_all()
        for existing in items:
            metadata = existing.migration_metadata or {}
            if metadata.get("legacy_anchor_id") == legacy_id_value:
                return await self.update(plan.model_copy(update={"uuid": existing.uuid}))
        return await self.create(plan)
