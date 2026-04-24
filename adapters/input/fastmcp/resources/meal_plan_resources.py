import json
from uuid import UUID as StdUUID

import fastmcp
from uuid6 import UUID

from adapters.input.fastmcp.dependencies import inject_tenant_uri
from adapters.input.schemas.meal_plan_schema import MealPlanSchema
from application.services.meal_plan_service import MealPlanService
from arclith.domain.ports.logger import Logger

_SAMPLE_LIMIT = 5
_RECENT_LIMIT = 10


class MealPlanResources:
    def __init__(self, service: MealPlanService, logger: Logger, mcp: fastmcp.FastMCP) -> None:
        self._service = service
        self._logger = logger
        self._mcp = mcp
        self._register_resources()

    @staticmethod
    def _to_uuid6(uuid: StdUUID) -> UUID:
        return UUID(str(uuid))

    def _register_resources(self) -> None:
        service = self._service
        logger = self._logger
        to_uuid6 = self._to_uuid6

        @self._mcp.resource("resource://meal-plans/sample")
        async def sample_meal_plans_resource(ctx: fastmcp.Context) -> str:
            """First 5 meal_plans ordered by creation date — quick dataset preview."""
            await inject_tenant_uri(ctx)
            items = await service.find_all()
            sample = sorted(items, key=lambda i: i.created_at)[:_SAMPLE_LIMIT]
            return json.dumps([MealPlanSchema.model_validate(i).model_dump(mode="json") for i in sample])

        @self._mcp.resource("resource://meal-plans/recent")
        async def recent_meal_plans_resource(ctx: fastmcp.Context) -> str:
            """Last 10 meal_plans by creation date, newest first."""
            await inject_tenant_uri(ctx)
            items = await service.find_all()
            recent = sorted(items, key=lambda i: i.created_at, reverse=True)[:_RECENT_LIMIT]
            return json.dumps([MealPlanSchema.model_validate(i).model_dump(mode="json") for i in recent])

        @self._mcp.resource("resource://meal-plan/{uuid}")
        async def get_meal_plan_resource(uuid: str, ctx: fastmcp.Context) -> str:
            """A single meal_plan by UUID."""
            await inject_tenant_uri(ctx)
            result = await service.read(to_uuid6(StdUUID(uuid)))
            if result is None:
                logger.warning("⚠️ MealPlan not found via MCP resource", uuid=uuid)
                return json.dumps(None)
            return json.dumps(MealPlanSchema.model_validate(result).model_dump(mode="json"))
