from abc import ABC, abstractmethod
from uuid import UUID

from domain.models.ingredient_snapshot import IngredientSnapshot
from domain.models.recipe_snapshot import RecipeSnapshot


class RecipeClient(ABC):
    @abstractmethod
    async def get_recipe_snapshot(self, recipe_uuid: UUID) -> RecipeSnapshot:
        pass

    @abstractmethod
    async def get_recipe_status(self, recipe_uuid: UUID) -> dict[str, str | int | None]:
        pass

    @abstractmethod
    async def get_ingredient_snapshot(self, ingredient_uuid: UUID) -> IngredientSnapshot:
        pass

    @abstractmethod
    async def list_eligible_recipes(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        pass
