"""MCP resources."""

import fastmcp

from arclith import Arclith
from adapters.input.fastmcp.resources.meal_plan_resources import MealPlanResources
from infrastructure.containers.meal_plan_container import build_meal_plan_service

__all__ = ["MealPlanResources"]


def register_resources(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
    service, logger = build_meal_plan_service(arclith)
    MealPlanResources(service, logger, mcp)
