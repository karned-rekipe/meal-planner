from unittest.mock import AsyncMock, patch

import fastmcp
import pytest

from adapters.input.fastmcp.prompts import MealPlanPrompts
from application.services.meal_plan_service import MealPlanService
from domain.models.meal_plan import MealPlan


@pytest.fixture
def mcp_app():
    return fastmcp.FastMCP("test")


@pytest.fixture
def service(repo, logger):
    return MealPlanService(repo, logger)


@pytest.fixture
async def client(service, logger, mcp_app):
    with patch("adapters.input.fastmcp.prompts.meal_plan_prompts.inject_tenant_uri", new=AsyncMock()):
        MealPlanPrompts(service, logger, mcp_app)
        async with fastmcp.Client(mcp_app) as c:
            yield c


def _text(result) -> str:
    return result.messages[0].content.text


# --- check_duplicate ---

async def test_check_duplicate_contains_name(client):
    result = await client.get_prompt("check_duplicate", {"meal_plan_name": "Farine"})
    assert "Farine" in _text(result)


async def test_check_duplicate_mentions_list_tool(client):
    result = await client.get_prompt("check_duplicate", {"meal_plan_name": "Sel"})
    assert "list_meal_plans" in _text(result)


# --- explore_meal_plans ---

async def test_explore_empty_catalog(client):
    result = await client.get_prompt("explore_meal_plans", {})
    assert "No meal_plans available" in _text(result)


async def test_explore_lists_meal_plan_names(client, service):
    await service.create(MealPlan(name="Farine"))
    await service.create(MealPlan(name="Sel"))
    result = await client.get_prompt("explore_meal_plans", {})
    text = _text(result)
    assert "Farine" in text
    assert "Sel" in text


async def test_explore_shows_total_count(client, service):
    for i in range(3):
        await service.create(MealPlan(name=f"Item {i}"))
    result = await client.get_prompt("explore_meal_plans", {})
    assert "3" in _text(result)


# --- mcp_help ---

async def test_mcp_help_lists_tools(client):
    text = _text(await client.get_prompt("mcp_help", {}))
    assert "create_meal_plan" in text
    assert "list_meal_plans" in text
    assert "purge_meal_plans" in text


async def test_mcp_help_lists_prompts(client):
    text = _text(await client.get_prompt("mcp_help", {}))
    assert "check_duplicate" in text
    assert "explore_meal_plans" in text
    assert "mcp_help" in text


async def test_mcp_help_lists_resources(client):
    text = _text(await client.get_prompt("mcp_help", {}))
    assert "resource://meal-plans/sample" in text
    assert "resource://meal-plans/recent" in text
    assert "resource://meal-plan/{uuid}" in text
