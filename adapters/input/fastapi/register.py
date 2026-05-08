from adapters.input.fastapi.routers import (
    AdminRouter,
    HouseholdMemberRouter,
    HouseholdScheduleRouter,
    MealPlanRouter,
    TenantPreferencesRouter,
)
from arclith import Arclith
from fastapi import FastAPI
from infrastructure.containers.meal_plan_container import build_meal_plan_service
from infrastructure.purge_registry import purge_registry


def register_routers(app: FastAPI, arclith: Arclith) -> None:
    service, logger = build_meal_plan_service(arclith)
    purge_registry.register("meal_plans", service.purge)
    app.include_router(MealPlanRouter(service, logger).router)
    app.include_router(TenantPreferencesRouter(service, logger).router)
    app.include_router(HouseholdMemberRouter(service, logger).router)
    app.include_router(HouseholdScheduleRouter(service, logger).router)
    app.include_router(AdminRouter(purge_registry).router)
