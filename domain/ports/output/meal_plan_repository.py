from abc import abstractmethod
from datetime import date
from uuid import UUID as StdUUID

from arclith.domain.ports.repository import Repository
from domain.models.enums import MealPlanStatus
from domain.models.legacy_meal_plan_entry import LegacyMealPlanEntry
from domain.models.meal_plan import MealPlan


class MealPlanRepository(Repository[MealPlan]):
    @abstractmethod
    async def find_by_name(self, name: str) -> list[MealPlan]:
        pass

    @abstractmethod
    async def find_page_by_name(self, name: str, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        """Return a page of meal_plans matching name filter and the total count."""
        pass

    @abstractmethod
    async def find_page_filtered(
        self,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        """Return meal plans matching optional V3 filters and total count."""
        pass

    @abstractmethod
    async def find_overlapping_confirmed(
        self,
        date_start: date,
        date_end: date,
        exclude_uuid: StdUUID | None = None,
    ) -> list[MealPlan]:
        pass

    @abstractmethod
    async def find_recent_recipe_uuids(
        self,
        since: date,
        statuses: tuple[MealPlanStatus, ...] = (MealPlanStatus.CONFIRMED, MealPlanStatus.DONE),
    ) -> set[StdUUID]:
        pass

    @abstractmethod
    async def find_legacy_entries(self, date_start: date, date_end: date) -> list[LegacyMealPlanEntry]:
        pass

    @abstractmethod
    async def upsert_by_legacy_id(self, legacy_id_value: int, plan: MealPlan) -> MealPlan:
        pass
