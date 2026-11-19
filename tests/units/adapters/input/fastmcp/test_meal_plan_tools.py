import json
from unittest.mock import AsyncMock, patch

import fastmcp
import pytest

from adapters.input.fastmcp.tools import AdminMCP, MealPlanMCP
from adapters.output.memory.repository import (
    InMemoryHouseholdScheduleRepository,
    InMemorySchoolVacationPeriodRepository,
)
from application.services.meal_plan_service import MealPlanService
from tests.units.factories import DEFAULT_DATE_START, meal_plan_payload


@pytest.fixture
def mcp_app():
    return fastmcp.FastMCP("test")


@pytest.fixture
def service(repo, logger):
    return MealPlanService(
        repo,
        logger,
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=InMemorySchoolVacationPeriodRepository(),
    )


@pytest.fixture
async def client(service, logger, mcp_app):
    with patch("adapters.input.fastmcp.tools.meal_plan_tools.inject_tenant_uri", new=AsyncMock()):
        with patch("adapters.input.fastmcp.tools.meal_plan_tools.require_auth_mcp", new=AsyncMock(return_value={"sub": "test-user"})):
            with patch("adapters.input.fastmcp.tools.admin_tools.require_auth_mcp", new=AsyncMock(return_value={"sub": "test-user"})):
                from infrastructure.purge_registry import PurgeRegistry

                registry = PurgeRegistry()
                registry.register("meal_plans", service.purge)
                MealPlanMCP(service, logger, mcp_app)
                AdminMCP(registry, logger, mcp_app)
                async with fastmcp.Client(mcp_app) as c:
                    yield c


def _data(result) -> dict | list | None:
    if not result.content:
        return result.data
    return json.loads(result.content[0].text)


def _payload(name: str = "Semaine test") -> dict:
    return meal_plan_payload(name)


@pytest.fixture
async def created(client) -> dict:
    result = await client.call_tool("create_meal_plan", {"payload": _payload()})
    data = _data(result)
    assert isinstance(data, dict)
    return data


async def test_create_returns_plan(client):
    result = await client.call_tool("create_meal_plan", {"payload": _payload("Semaine MCP")})
    data = _data(result)
    assert data["name"] == "Semaine MCP"
    assert len(data["slots"]) == 14


async def test_get_found(client, created):
    result = await client.call_tool("get_meal_plan", {"uuid": created["uuid"]})
    assert _data(result)["name"] == "Semaine test"


async def test_get_not_found_returns_none(client):
    result = await client.call_tool("get_meal_plan", {"uuid": "01951234-5678-7abc-def0-000000000000"})
    assert _data(result) is None


async def test_update_changes_name(client, created):
    payload = {
        "name": "Semaine ajustée",
        "date_start": created["date_start"],
        "date_end": created["date_end"],
        "status": created["status"],
        "slots": created["slots"],
    }
    await client.call_tool(
        "update_meal_plan",
        {"uuid": created["uuid"], "expected_version": created["version"], "payload": payload},
    )
    result = await client.call_tool("get_meal_plan", {"uuid": created["uuid"]})
    assert _data(result)["name"] == "Semaine ajustée"


async def test_patch_headcount(client, created):
    result = await client.call_tool(
        "patch_meal_plan_slots",
        {
            "uuid": created["uuid"],
            "expected_version": created["version"],
            "payload": {
                "operations": [
                    {
                        "op": "set_headcount",
                        "slot_date": DEFAULT_DATE_START.isoformat(),
                        "slot_code": "lunch",
                        "headcount": 2,
                    }
                ]
            },
        },
    )
    slot = next(item for item in _data(result)["slots"] if item["date"] == DEFAULT_DATE_START.isoformat() and item["slot_code"] == "lunch")
    assert slot["headcount"] == 2


async def test_delete_hides_meal_plan(client, created):
    await client.call_tool("delete_meal_plan", {"uuid": created["uuid"], "expected_version": created["version"]})
    result = await client.call_tool("get_meal_plan", {"uuid": created["uuid"]})
    assert _data(result) is None


async def test_list_all(client):
    await client.call_tool("create_meal_plan", {"payload": _payload("Semaine 1")})
    await client.call_tool("create_meal_plan", {"payload": _payload("Semaine 2")})
    result = await client.call_tool("list_meal_plans", {})
    assert len(_data(result)["data"]) == 2


async def test_list_filtered(client):
    await client.call_tool("create_meal_plan", {"payload": _payload("Semaine draft")})
    result = await client.call_tool("list_meal_plans", {"status": "draft"})
    items = _data(result)["data"]
    assert len(items) == 1
    assert items[0]["status"] == "draft"


async def test_transition_status(client, created):
    result = await client.call_tool(
        "transition_meal_plan_status",
        {"uuid": created["uuid"], "expected_version": created["version"], "target_status": "confirmed"},
    )
    assert _data(result)["status"] == "confirmed"


async def test_purge_returns_count(client):
    result = await client.call_tool("purge_all", {})
    data = _data(result)
    assert "purged" in data
    assert "total" in data


async def test_household_schedule_tools(client):
    current = _data(await client.call_tool("get_household_schedule", {}))
    result = await client.call_tool(
        "update_household_schedule",
        {
            "expected_version": current["version"],
            "payload": {
                "school_zone": "A",
                "rules": [
                    {
                        "week_parity": "even",
                        "school_period_type": "regular",
                        "day_of_week": "monday",
                        "meal_slot_code": "lunch",
                        "headcount": 4,
                    }
                ],
            },
        },
    )

    data = _data(result)
    assert data["school_zone"] == "A"
    assert data["rules"][0]["headcount"] == 4


async def test_school_vacation_period_tools(client):
    result = await client.call_tool(
        "create_school_vacation_period",
        {
            "payload": {
                "source": "manual",
                "school_zone": None,
                "name": "Vacances manuelles",
                "start_date": "2026-01-05",
                "end_date": "2026-01-11",
            }
        },
    )
    created = _data(result)

    list_result = await client.call_tool("list_school_vacation_periods", {})
    periods = _data(list_result)

    assert created["name"] == "Vacances manuelles"
    assert periods[0]["uuid"] == created["uuid"]

    updated_result = await client.call_tool(
        "update_school_vacation_period",
        {
            "uuid": created["uuid"],
            "expected_version": created["version"],
            "payload": {
                "source": "manual",
                "school_zone": None,
                "name": "Vacances ajustées",
                "start_date": "2026-01-06",
                "end_date": "2026-01-12",
            },
        },
    )
    updated = _data(updated_result)
    delete_result = await client.call_tool(
        "delete_school_vacation_period",
        {"uuid": created["uuid"], "expected_version": updated["version"]},
    )

    assert updated["name"] == "Vacances ajustées"
    assert _data(delete_result)["deleted"] is True
