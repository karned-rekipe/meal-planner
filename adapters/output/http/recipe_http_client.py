from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from domain.exceptions import IngredientNotFound, RecipeNotEligible, RecipeNotFound
from domain.models.ingredient_snapshot import IngredientSnapshot
from domain.models.recipe_snapshot import RecipeSnapshot, RecipeSnapshotIngredient
from domain.ports.output.recipe_client import RecipeClient


class RecipeHttpClient(RecipeClient):
    def __init__(self, base_url: str, tenant_uri: str | None = None, api_token: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._tenant_uri = tenant_uri
        self._api_token = api_token

    async def get_recipe_snapshot(self, recipe_uuid: UUID) -> RecipeSnapshot:
        recipe = await self._get_recipe_payload(recipe_uuid)
        status = recipe.get("status")
        ingredients = recipe.get("ingredients") or []
        if status != "active" or not ingredients:
            raise RecipeNotEligible(f"Recipe {recipe_uuid} is not meal-planner eligible")

        description = recipe.get("description")
        short_description = description[:200] if isinstance(description, str) and description else None
        total_duration = self._calculate_total_duration(recipe)
        return RecipeSnapshot(
            recipe_uuid=recipe_uuid,
            title=str(recipe.get("name") or ""),
            short_description=short_description,
            servings_default=int(recipe.get("servings") or 1),
            total_duration_min=total_duration,
            ingredients=[self._ingredient_to_snapshot(item) for item in ingredients],
            snapshot_taken_at=datetime.now(timezone.utc),
            recipe_version=int(recipe["version"]) if recipe.get("version") is not None else None,
        )

    async def get_recipe_status(self, recipe_uuid: UUID) -> dict[str, str | int | None]:
        recipe = await self._get_recipe_payload(recipe_uuid)
        version = recipe.get("version")
        return {
            "status": str(recipe.get("status") or "unknown"),
            "version": int(version) if version is not None else None,
        }

    async def get_ingredient_snapshot(self, ingredient_uuid: UUID) -> IngredientSnapshot:
        ingredient = await self._get_ingredient_payload(ingredient_uuid)
        return IngredientSnapshot(
            ingredient_uuid=ingredient_uuid,
            name=str(ingredient.get("name") or ""),
            unit=ingredient.get("unit"),
        )

    async def list_eligible_recipes(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        params: dict[str, str | int | bool] = {
            "page": page,
            "per_page": page_size,
            "meal_planner_eligible": True,
            "status": "active",
        }
        if search:
            params["name"] = search
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self._base_url}/v1/recipes/",
                params=params,
                headers=self._headers(),
            )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", []), int(payload.get("pagination", {}).get("total", 0))

    async def _get_recipe_payload(self, recipe_uuid: UUID) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self._base_url}/v1/recipes/{recipe_uuid}",
                headers=self._headers(),
            )
        if response.status_code == 404:
            raise RecipeNotFound(f"Recipe {recipe_uuid} not found")
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RecipeNotFound(f"Recipe {recipe_uuid} response is invalid")
        return data

    async def _get_ingredient_payload(self, ingredient_uuid: UUID) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self._base_url}/v1/ingredients/{ingredient_uuid}",
                headers=self._headers(),
            )
        if response.status_code == 404:
            raise IngredientNotFound(f"Ingredient {ingredient_uuid} not found")
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise IngredientNotFound(f"Ingredient {ingredient_uuid} response is invalid")
        return data

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._tenant_uri:
            headers["X-Tenant-URI"] = self._tenant_uri
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    @staticmethod
    def _ingredient_to_snapshot(item: dict[str, Any]) -> RecipeSnapshotIngredient:
        season_months = item.get("season_months") or []
        rayon = item.get("rayon")
        group = item.get("group")
        return RecipeSnapshotIngredient(
            ingredient_uuid=UUID(str(item["ingredient_uuid"])),
            name=str(item.get("name") or ""),
            quantity=float(item.get("quantity") or 0),
            unit=str(item.get("unit") or ""),
            season_months=season_months,
            green_score=item.get("green_score"),
            rayon=rayon.get("name") if isinstance(rayon, dict) else item.get("rayon"),
            group=group.get("name") if isinstance(group, dict) else item.get("group"),
            supplier_uuid=UUID(str(item["main_supplier_uuid"])) if item.get("main_supplier_uuid") else None,
        )

    @staticmethod
    def _calculate_total_duration(recipe: dict[str, Any]) -> int | None:
        total = 0
        for step in recipe.get("steps") or []:
            for key in ("preparation_time", "cooking_time", "rest_time"):
                value = step.get(key)
                if value is not None:
                    total += int(value)
        return total or None
