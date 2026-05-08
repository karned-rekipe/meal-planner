"""FastAPI routers."""

from adapters.input.fastapi.routers.admin_router import AdminRouter
from adapters.input.fastapi.routers.household_member_router import HouseholdMemberRouter
from adapters.input.fastapi.routers.household_schedule_router import HouseholdScheduleRouter
from adapters.input.fastapi.routers.meal_plan_router import MealPlanRouter
from adapters.input.fastapi.routers.tenant_preferences_router import TenantPreferencesRouter

__all__ = ["AdminRouter", "HouseholdMemberRouter", "HouseholdScheduleRouter", "MealPlanRouter", "TenantPreferencesRouter"]
