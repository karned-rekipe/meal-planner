from arclith.adapters.output.memory.repository import InMemoryRepository
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
