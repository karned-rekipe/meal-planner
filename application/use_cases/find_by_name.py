from arclith.domain.ports.logger import Logger
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository


class FindByNameUseCase:
    def __init__(self, repository: MealPlanRepository, logger: Logger) -> None:
        self._repository = repository
        self._logger = logger

    async def execute(self, name: str) -> list[MealPlan]:
        self._logger.info("🔍 Finding meal_plans by name", name=name)
        result = [i for i in await self._repository.find_by_name(name) if not i.is_deleted]
        self._logger.info("✅ MealPlans found", name=name, count=len(result))
        return result

