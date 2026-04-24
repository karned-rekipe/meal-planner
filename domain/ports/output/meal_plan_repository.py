from abc import abstractmethod

from arclith.domain.ports.repository import Repository
from domain.models.meal_plan import MealPlan


class MealPlanRepository(Repository[MealPlan]):
    @abstractmethod
    async def find_by_name(self, name: str) -> list[MealPlan]:
        pass

    @abstractmethod
    async def find_page_by_name(self, name: str, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        """Return a page of meal_plans matching name filter and the total count."""
        pass

