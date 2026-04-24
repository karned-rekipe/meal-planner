"""FastAPI routers."""

from adapters.input.fastapi.routers.admin_router import AdminRouter
from adapters.input.fastapi.routers.meal_plan_router import MealPlanRouter

__all__ = ["AdminRouter", "MealPlanRouter"]

