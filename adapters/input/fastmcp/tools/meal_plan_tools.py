from datetime import date
from typing import Annotated
from uuid import UUID as StdUUID

import fastmcp
from pydantic import Field
from uuid6 import UUID

from adapters.input.fastmcp.dependencies import inject_tenant_uri, require_auth_mcp
from adapters.input.schemas.meal_plan_schema import (
    MealPlanCreateSchema,
    MealPlanPatchSchema,
    MealPlanSchema,
    MealPlanUpdateSchema,
    meal_plan_create_payload_to_domain,
    meal_plan_to_summary,
    meal_plan_update_payload_to_domain,
)
from adapters.input.schemas.household_schedule_schema import (
    HouseholdScheduleUpdateSchema,
    SchoolVacationPeriodPayload,
    SchoolVacationPeriodSchema,
    household_schedule_to_schema,
)
from adapters.input.schemas.tenant_preferences_schema import (
    TenantPreferencesSchema,
    TenantPreferencesUpdateSchema,
    tenant_preferences_update_payload_to_domain,
)
from application.services.meal_plan_service import ItemRef
from application.services.meal_plan_service import MealPlanService
from arclith.domain.ports.logger import Logger
from domain.models.enums import MealPlanStatus


class MealPlanMCP:
    def __init__(self, service: MealPlanService, logger: Logger, mcp: fastmcp.FastMCP) -> None:
        self._service = service
        self._logger = logger
        self._mcp = mcp
        self._register_tools()

    @staticmethod
    def _to_uuid6(uuid: StdUUID) -> UUID:
        return UUID(str(uuid))

    def _register_tools(self) -> None:
        service = self._service
        logger = self._logger
        to_uuid6 = self._to_uuid6

        @self._mcp.tool
        async def create_meal_plan(payload: MealPlanCreateSchema, ctx: fastmcp.Context | None = None) -> dict:
            """Create a meal plan for a free date period."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.create(meal_plan_create_payload_to_domain(payload))
            logger.info("✅ MealPlan created via MCP", uuid=str(result.uuid), name=result.name)
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def get_meal_plan(
            uuid: Annotated[str, Field(description="Meal plan UUID")],
            ctx: fastmcp.Context | None = None,
        ) -> dict | None:
            """Read one meal plan with recipe status enrichment."""
            await inject_tenant_uri(ctx)
            result = await service.read(to_uuid6(StdUUID(uuid)))
            if result is None:
                logger.warning("⚠️ MealPlan not found via MCP", uuid=uuid)
                return None
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def list_meal_plans(
            status: MealPlanStatus | None = None,
            date_from: date | None = None,
            date_to: date | None = None,
            page: int = 1,
            page_size: int = 20,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """List meal plans with V3 filters."""
            await inject_tenant_uri(ctx)
            offset = (page - 1) * page_size
            items, total = await service.find_page_filtered(
                status=status,
                date_from=date_from,
                date_to=date_to,
                offset=offset,
                limit=page_size,
            )
            return {
                "data": [meal_plan_to_summary(item).model_dump(mode="json") for item in items],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }

        @self._mcp.tool
        async def update_meal_plan(
            uuid: str,
            expected_version: int,
            payload: MealPlanUpdateSchema,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Replace a meal plan with optimistic locking."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            existing = await service.read(to_uuid6(StdUUID(uuid)))
            if existing is None:
                return {"error": "not_found"}
            result = await service.update_with_expected(
                to_uuid6(StdUUID(uuid)),
                meal_plan_update_payload_to_domain(existing, payload),
                expected_version,
            )
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def patch_meal_plan_slots(
            uuid: str,
            expected_version: int,
            payload: MealPlanPatchSchema,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Patch slots and items atomically."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.patch_slots(
                to_uuid6(StdUUID(uuid)),
                [operation.to_service_operation() for operation in payload.operations],
                expected_version,
            )
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def transition_meal_plan_status(
            uuid: str,
            expected_version: int,
            target_status: MealPlanStatus,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Transition a meal plan status."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.transition_status(to_uuid6(StdUUID(uuid)), target_status, expected_version)
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def delete_meal_plan(
            uuid: str,
            expected_version: int,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Hard-delete a draft or abandoned meal plan."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            await service.delete_with_expected(to_uuid6(StdUUID(uuid)), expected_version)
            return {"deleted": True}

        @self._mcp.tool
        async def refresh_recipe_snapshots(
            uuid: str,
            expected_version: int,
            items: list[ItemRef],
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Refresh recipe snapshots for selected meal items."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.refresh_recipe_snapshots(to_uuid6(StdUUID(uuid)), items, expected_version)
            return MealPlanSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def get_meal_plan_shopping_projection(uuid: str, ctx: fastmcp.Context | None = None) -> dict:
            """Build the shopping projection for a meal plan."""
            await inject_tenant_uri(ctx)
            return await service.build_shopping_projection(to_uuid6(StdUUID(uuid)))

        @self._mcp.tool
        async def get_tenant_preferences(ctx: fastmcp.Context | None = None) -> dict:
            """Read tenant food preferences."""
            await inject_tenant_uri(ctx)
            result = await service.get_tenant_preferences()
            return TenantPreferencesSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def update_tenant_preferences(
            expected_version: int,
            payload: TenantPreferencesUpdateSchema,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Update tenant food preferences."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.update_tenant_preferences(
                tenant_preferences_update_payload_to_domain(payload),
                expected_version,
            )
            return TenantPreferencesSchema.model_validate(result).model_dump(mode="json")

        @self._mcp.tool
        async def get_household_schedule(ctx: fastmcp.Context | None = None) -> dict:
            """Read the tenant household headcount schedule and all configured rules."""
            await inject_tenant_uri(ctx)
            schedule, rules = await service.get_household_schedule()
            return household_schedule_to_schema(schedule, rules).model_dump(mode="json")

        @self._mcp.tool
        async def update_household_schedule(
            expected_version: int,
            payload: HouseholdScheduleUpdateSchema,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Replace the tenant household headcount schedule rules."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            existing, _ = await service.get_household_schedule()
            schedule, rules = await service.update_household_schedule(
                payload.to_domain(),
                [rule.to_domain(existing.uuid) for rule in payload.rules],
                expected_version,
            )
            return household_schedule_to_schema(schedule, rules).model_dump(mode="json")

        @self._mcp.tool
        async def list_school_vacation_periods(ctx: fastmcp.Context | None = None) -> list[dict]:
            """List tenant school vacation periods used by household scheduling."""
            await inject_tenant_uri(ctx)
            return [
                SchoolVacationPeriodSchema.model_validate(period, from_attributes=True).model_dump(mode="json")
                for period in await service.list_school_vacation_periods()
            ]

        @self._mcp.tool
        async def create_school_vacation_period(
            payload: SchoolVacationPeriodPayload,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Create a manual or official school vacation period for the tenant."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.create_school_vacation_period(payload.to_domain())
            return SchoolVacationPeriodSchema.model_validate(result, from_attributes=True).model_dump(mode="json")

        @self._mcp.tool
        async def update_school_vacation_period(
            uuid: str,
            expected_version: int,
            payload: SchoolVacationPeriodPayload,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Update a school vacation period with optimistic locking."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.update_school_vacation_period(
                to_uuid6(StdUUID(uuid)),
                payload.to_domain(),
                expected_version,
            )
            return SchoolVacationPeriodSchema.model_validate(result, from_attributes=True).model_dump(mode="json")

        @self._mcp.tool
        async def delete_school_vacation_period(
            uuid: str,
            expected_version: int,
            ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Delete a school vacation period."""
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            await service.delete_school_vacation_period(to_uuid6(StdUUID(uuid)), expected_version)
            return {"deleted": True}

        @self._mcp.tool
        async def find_recent_recipe_uuids(days: int = 30, ctx: fastmcp.Context | None = None) -> list[str]:
            """Return recipe UUIDs used in recent confirmed/done plans."""
            await inject_tenant_uri(ctx)
            return [str(item) for item in await service.find_recent_recipe_uuids(days=days)]
