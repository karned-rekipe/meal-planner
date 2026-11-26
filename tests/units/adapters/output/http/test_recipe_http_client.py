import json
from uuid import UUID

import httpx
import pytest
from uuid6 import uuid7

from adapters.output.http import recipe_http_client as recipe_http_client_module
from adapters.output.http.recipe_http_client import RecipeHttpClient
from domain.exceptions import IngredientNotFound, RecipeNotEligible, RecipeNotFound


def _use_mock_transport(monkeypatch, handler) -> None:
    original_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def build_client(*args, **kwargs):
        return original_async_client(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(recipe_http_client_module.httpx, "AsyncClient", build_client)


async def test_recipe_client_hydrates_snapshots_status_ingredients_and_listing(monkeypatch):
    recipe_uuid = uuid7()
    ingredient_uuid = uuid7()
    supplier_uuid = uuid7()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(f"/v1/recipes/{recipe_uuid}"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "name": "Soupe de saison",
                        "description": "A" * 240,
                        "servings": 4,
                        "status": "active",
                        "version": 7,
                        "steps": [
                            {"preparation_time": 10, "cooking_time": 20, "rest_time": None},
                            {"preparation_time": 5, "cooking_time": None, "rest_time": 2},
                        ],
                        "ingredients": [
                            {
                                "ingredient_uuid": str(ingredient_uuid),
                                "name": "Carotte",
                                "quantity": 3,
                                "unit": "pièce",
                                "season_months": {"1": 2, "2": 0, "12": 1},
                                "green_score": 92,
                                "rayon": {"name": "Fruits et légumes"},
                                "group": "Légumes",
                                "main_supplier_uuid": str(supplier_uuid),
                            }
                        ],
                    }
                },
            )
        if request.url.path.endswith(f"/v1/ingredients/{ingredient_uuid}"):
            return httpx.Response(200, json={"data": {"name": "Carotte", "unit": "kg"}})
        if request.url.path.endswith("/v1/recipes/"):
            assert request.url.params["meal_planner_eligible"] == "true"
            assert request.url.params["status"] == "active"
            assert request.url.params["name"] == "soupe"
            return httpx.Response(200, json={"data": [{"uuid": str(recipe_uuid)}], "pagination": {"total": 1}})
        return httpx.Response(500)

    _use_mock_transport(monkeypatch, handler)
    client = RecipeHttpClient("https://recipe.example/", tenant_uri="foyer", api_token="token")

    snapshot = await client.get_recipe_snapshot(recipe_uuid)
    status = await client.get_recipe_status(recipe_uuid)
    ingredient = await client.get_ingredient_snapshot(ingredient_uuid)
    recipes, total = await client.list_eligible_recipes(page=2, page_size=10, search="soupe")

    assert snapshot.title == "Soupe de saison"
    assert snapshot.short_description == "A" * 200
    assert snapshot.total_duration_min == 37
    assert snapshot.recipe_version == 7
    assert snapshot.ingredients[0].season_months == [1, 12]
    assert snapshot.ingredients[0].rayon == "Fruits et légumes"
    assert snapshot.ingredients[0].group == "Légumes"
    assert snapshot.ingredients[0].supplier_uuid == supplier_uuid
    assert status == {"status": "active", "version": 7}
    assert ingredient.name == "Carotte"
    assert ingredient.unit == "kg"
    assert recipes == [{"uuid": str(recipe_uuid)}]
    assert total == 1
    assert all(request.headers["X-Tenant-URI"] == "foyer" for request in requests)
    assert all(request.headers["Authorization"] == "Bearer token" for request in requests)


@pytest.mark.parametrize(
    ("status", "ingredients"),
    [("draft", [{"ingredient_uuid": str(uuid7())}]), ("active", [])],
)
async def test_recipe_snapshot_rejects_ineligible_recipes(monkeypatch, status, ingredients):
    recipe_uuid = uuid7()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"status": status, "ingredients": ingredients}})

    _use_mock_transport(monkeypatch, handler)

    with pytest.raises(RecipeNotEligible):
        await RecipeHttpClient("https://recipe.example").get_recipe_snapshot(recipe_uuid)


@pytest.mark.parametrize("kind", ["recipe", "ingredient"])
@pytest.mark.parametrize("response_kind", ["missing", "invalid"])
async def test_recipe_client_classifies_missing_and_invalid_payloads(monkeypatch, kind, response_kind):
    resource_uuid = uuid7()

    def handler(request: httpx.Request) -> httpx.Response:
        if response_kind == "missing":
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps({"data": []}).encode())

    _use_mock_transport(monkeypatch, handler)
    client = RecipeHttpClient("https://recipe.example")

    if kind == "recipe":
        with pytest.raises(RecipeNotFound):
            await client.get_recipe_status(resource_uuid)
    else:
        with pytest.raises(IngredientNotFound):
            await client.get_ingredient_snapshot(resource_uuid)


async def test_recipe_client_propagates_http_errors_and_handles_empty_optional_values(monkeypatch):
    recipe_uuid = uuid7()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/recipes/"):
            return httpx.Response(200, json={})
        return httpx.Response(503)

    _use_mock_transport(monkeypatch, handler)
    client = RecipeHttpClient("https://recipe.example")

    recipes, total = await client.list_eligible_recipes(search=None)
    assert recipes == []
    assert total == 0
    assert client._headers() == {}
    assert client._calculate_total_duration({"steps": []}) is None

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_recipe_status(recipe_uuid)


def test_ingredient_snapshot_supports_flat_catalog_fields():
    ingredient_uuid = uuid7()
    snapshot = RecipeHttpClient._ingredient_to_snapshot(
        {
            "ingredient_uuid": str(ingredient_uuid),
            "name": "Farine",
            "quantity": None,
            "unit": None,
            "rayon": "Épicerie",
            "group": "Céréales",
        }
    )

    assert snapshot.ingredient_uuid == UUID(str(ingredient_uuid))
    assert snapshot.quantity == 0
    assert snapshot.unit == ""
    assert snapshot.rayon == "Épicerie"
    assert snapshot.group == "Céréales"
    assert snapshot.supplier_uuid is None
