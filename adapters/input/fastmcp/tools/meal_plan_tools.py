import fastmcp
from pydantic import Field
from uuid6 import UUID

from adapters.input.fastmcp.dependencies import inject_tenant_uri, require_auth_mcp
from adapters.input.schemas.meal_plan_schema import MealPlanSchema
from application.services.meal_plan_service import MealPlanService
from arclith.domain.ports.logger import Logger
from domain.models.meal_plan import MealPlan
from typing import Annotated
from uuid import UUID as StdUUID


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
        async def create_meal_plan(
                name: Annotated[str, Field(
                    description = "Nom de l'ingrédient (ex. 'Farine de blé', 'Sel fin'). Sera normalisé (espaces rognés).",
                    examples = ["Farine de blé", "Sel fin"])],
                ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Create a new reusable meal_plan.

            Returns the created meal_plan with its generated UUID.
            Once created, use `link_meal_plan_to_recipe` to attach it to a recipe.
            Fields returned: uuid, name, created_at, updated_at, version.
            """
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            result = await service.create(MealPlan(name = name))
            logger.info("✅ MealPlan created via MCP", uuid = str(result.uuid), name = result.name)
            return MealPlanSchema.model_validate(result).model_dump()

        @self._mcp.tool
        async def get_meal_plan(
                uuid: Annotated[str, Field(description = "UUID (UUIDv7) de l'ingrédient à récupérer.",
                                           examples = ["01951234-5678-7abc-def0-123456789abc"])],
                ctx: fastmcp.Context | None = None,
        ) -> dict | None:
            """Get an meal_plan by its UUID.

            Returns the full meal_plan object or null if not found.
            Fields: uuid, name, created_at, updated_at, version.
            """
            await inject_tenant_uri(ctx)
            result = await service.read(to_uuid6(StdUUID(uuid)))
            if result is None:
                logger.warning("⚠️ MealPlan not found via MCP", uuid = uuid)
                return None
            logger.info("✅ MealPlan fetched via MCP", uuid = uuid, name = result.name)
            return MealPlanSchema.model_validate(result).model_dump()

        @self._mcp.tool
        async def update_meal_plan(
                uuid: Annotated[str, Field(description = "UUID (UUIDv7) de l'ingrédient à modifier.",
                                           examples = ["01951234-5678-7abc-def0-123456789abc"])],
                name: Annotated[str, Field(description = "Nouveau nom de l'ingrédient.",
                                           examples = ["Farine complète", "Gros sel"])],
                ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Replace name of an existing meal_plan.

            Full replacement (PUT semantics): name is overwritten.
            Returns the updated meal_plan.
            Note: updating an meal_plan does not propagate to recipes where it is already linked (snapshot model).
            """
            await inject_tenant_uri(ctx)
            result = await service.update(MealPlan(uuid = to_uuid6(StdUUID(uuid)), name = name))
            logger.info("✅ MealPlan updated via MCP", uuid = uuid, name = result.name)
            return MealPlanSchema.model_validate(result).model_dump()

        @self._mcp.tool
        async def delete_meal_plan(
                uuid: Annotated[str, Field(description = "UUID (UUIDv7) de l'ingrédient à supprimer.",
                                           examples = ["01951234-5678-7abc-def0-123456789abc"])],
                ctx: fastmcp.Context | None = None,
        ) -> None:
            """Soft-delete an meal_plan.

            The meal_plan is marked as deleted and excluded from list results.
            It is retained until the purge retention period expires.
            Use `purge_meal_plans` to permanently remove expired entries.
            """
            await require_auth_mcp(ctx)
            await inject_tenant_uri(ctx)
            await service.delete(to_uuid6(StdUUID(uuid)))
            logger.info("✅ MealPlan deleted via MCP", uuid = uuid)

        @self._mcp.tool
        async def list_meal_plans(
                name: Annotated[str | None, Field(default = None,
                                                  description = "Filtre optionnel : recherche partielle sur le nom, insensible à la casse. Ex: 'far' retournera 'Farine de blé'.",
                                                  examples = ["farine", None])] = None,
                ctx: fastmcp.Context | None = None,
        ) -> list[dict]:
            """List all active (non-deleted) meal_plans.

            Pass `name` for a partial, case-insensitive name filter.
            Each item: uuid, name, created_at, updated_at, version.
            Use these UUIDs with `link_meal_plan_to_recipe` to attach meal_plans to a recipe.
            """
            await inject_tenant_uri(ctx)
            items = await service.find_by_name(name) if name else await service.find_all()
            logger.info("✅ MealPlans listed via MCP", count = len(items), filter = name)
            return [MealPlanSchema.model_validate(i).model_dump() for i in items]

        @self._mcp.tool
        async def duplicate_meal_plan(
                uuid: Annotated[str, Field(description = "UUID (UUIDv7) de l'ingrédient à dupliquer.",
                                           examples = ["01951234-5678-7abc-def0-123456789abc"])],
                ctx: fastmcp.Context | None = None,
        ) -> dict:
            """Duplicate an meal_plan, assigning it a new UUID.

            Creates an independent copy with the same name.
            Returns the new meal_plan with its own UUID.
            """
            await inject_tenant_uri(ctx)
            result = await service.duplicate(to_uuid6(StdUUID(uuid)))
            logger.info("✅ MealPlan duplicated via MCP", source_uuid = uuid, new_uuid = str(result.uuid))
            return MealPlanSchema.model_validate(result).model_dump()

