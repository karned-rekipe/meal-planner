"""MCP prompts."""

import fastmcp

from arclith import Arclith
from adapters.input.fastmcp.prompts.meal_plan_prompts import MealPlanPrompts
from infrastructure.containers.meal_plan_container import build_meal_plan_service

__all__ = ["MealPlanPrompts"]


def register_prompts(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
    service, logger = build_meal_plan_service(arclith)
    MealPlanPrompts(service, logger, mcp)
