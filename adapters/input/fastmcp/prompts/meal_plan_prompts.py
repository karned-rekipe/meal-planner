import fastmcp

from adapters.input.fastmcp.dependencies import inject_tenant_uri
from application.services.meal_plan_service import MealPlanService
from arclith.domain.ports.logger import Logger

_EXPLORE_PREVIEW_LIMIT = 20


class MealPlanPrompts:
    def __init__(self, service: MealPlanService, logger: Logger, mcp: fastmcp.FastMCP) -> None:
        self._service = service
        self._logger = logger
        self._mcp = mcp
        self._register_prompts()

    def _register_prompts(self) -> None:
        service = self._service

        @self._mcp.prompt
        def check_duplicate(meal_plan_name: str) -> str:
            """Check for duplicates before creating a new meal_plan.

            Use this prompt before calling create_meal_plan.
            The LLM will guide you to call list_meal_plans with a partial
            name filter to surface any existing match.
            """
            return (
                f"Before creating the meal_plan '{meal_plan_name}', "
                "call list_meal_plans with a partial name filter to check for existing similar entries. "
                "If a match is found, suggest using the existing one instead of creating a duplicate."
            )

        @self._mcp.prompt
        async def explore_meal_plans(ctx: fastmcp.Context) -> str:
            """Explore and discover available meal_plans.

            Loads the current catalog and guides the LLM to help the user
            search by name or identify what is available.
            """
            await inject_tenant_uri(ctx)
            items = await service.find_all()
            if not items:
                snapshot = "No meal_plans available yet. Use create_meal_plan to add the first one."
            else:
                names = ", ".join(i.name for i in items[:_EXPLORE_PREVIEW_LIMIT])
                total = len(items)
                snapshot = f"{total} meal_plan(s) available: {names}{'...' if total > _EXPLORE_PREVIEW_LIMIT else '.'}"
            return (
                f"{snapshot}\n\n"
                "Help me explore these meal_plans: search by name, "
                "or suggest which ones to use for a given dish."
            )

        @self._mcp.prompt
        def mcp_help() -> str:
            """Overview of all MCP capabilities exposed by this server.

            Lists every tool, prompt, and resource with a short description.
            Use this as a starting point when discovering what this server can do.
            """
            return (
                "Here are all the capabilities exposed by this MCP server:\n\n"
                "**Tools** (actions):\n"
                "- create_meal_plan(name) — create a new meal_plan\n"
                "- get_meal_plan(uuid) — retrieve by UUID\n"
                "- update_meal_plan(uuid, name) — full replacement (PUT semantics)\n"
                "- delete_meal_plan(uuid) — soft-delete\n"
                "- list_meal_plans(name?) — list all active, optional partial name filter\n"
                "- duplicate_meal_plan(uuid) — clone with a new UUID\n"
                "- purge_meal_plans() — permanently remove expired soft-deleted entries\n\n"
                "**Prompts** (LLM guidance):\n"
                "- check_duplicate(meal_plan_name) — avoid duplicates before creating\n"
                "- explore_meal_plans — discover and filter available meal_plans\n"
                "- mcp_help — this overview\n\n"
                "**Resources** (read-only data):\n"
                "- resource://meal-plans/sample — first 5 meal_plans (quick dataset preview)\n"
                "- resource://meal-plans/recent — last 10 meal_plans by creation date, newest first\n"
                "- resource://meal-plan/{uuid} — single meal_plan by UUID\n"
            )
