from datetime import datetime, timezone
from uuid import UUID

from domain.models.ingredient_snapshot import IngredientSnapshot
from domain.models.recipe_snapshot import RecipeSnapshot
from domain.ports.output.recipe_client import RecipeClient


class StaticRecipeClient(RecipeClient):
    async def get_recipe_snapshot(self, recipe_uuid: UUID) -> RecipeSnapshot:
        return RecipeSnapshot(
            recipe_uuid=recipe_uuid,
            title=f"Recette {recipe_uuid}",
            short_description=None,
            servings_default=1,
            total_duration_min=None,
            ingredients=[],
            snapshot_taken_at=datetime.now(timezone.utc),
            recipe_version=1,
        )

    async def get_recipe_status(self, recipe_uuid: UUID) -> dict[str, str | int | None]:
        return {"status": "unknown", "version": None}

    async def get_ingredient_snapshot(self, ingredient_uuid: UUID) -> IngredientSnapshot:
        return IngredientSnapshot(
            ingredient_uuid=ingredient_uuid,
            name=f"Ingrédient {ingredient_uuid}",
            unit="x",
        )

    async def list_eligible_recipes(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        return [], 0
