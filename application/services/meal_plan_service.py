from application.use_cases import FindByNameUseCase
from arclith import BaseService, Logger
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository


class MealPlanService(BaseService[MealPlan]):
    def __init__(self, repository: MealPlanRepository, logger: Logger, retention_days: float | None = None) -> None:
        super().__init__(repository, logger, retention_days)
        self._meal_plan_repo = repository
        self._find_by_name_uc = FindByNameUseCase(repository, logger)

    async def find_by_name(self, name: str) -> list[MealPlan]:
        return await self._find_by_name_uc.execute(name)

    async def find_page_filtered(self, name: str | None = None, offset: int = 0, limit: int | None = None) -> tuple[list[MealPlan], int]:
        """Return a page of meal_plans (optionally filtered by name) and total count."""
        if name:
            return await self._meal_plan_repo.find_page_by_name(name, offset, limit)
        return await self._meal_plan_repo.find_page(offset, limit)

