"""MCP tools registration."""

import fastmcp
from adapters.input.fastmcp.tools import AdminMCP, MealPlanMCP
from arclith import Arclith
from infrastructure.containers.meal_plan_container import build_meal_plan_service
from infrastructure.purge_registry import purge_registry


def register_tools(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
    """Register all MCP tools."""
    service, logger = build_meal_plan_service(arclith)
    purge_registry.register("meal_plans", service.purge)
    MealPlanMCP(service, logger, mcp)
    AdminMCP(purge_registry, logger, mcp)

