from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from adapters.input.fastapi.dependencies import inject_tenant_uri
from adapters.input.fastapi.routers.meal_plan_router import MealPlanRouter
from adapters.input.schemas.tenant_preferences_schema import (
    TenantPreferencesSchema,
    TenantPreferencesUpdateSchema,
    tenant_preferences_update_payload_to_domain,
)
from application.services.meal_plan_service import MealPlanService
from arclith.adapters.input.schemas.response_wrapper import ApiResponse, success_response
from arclith.domain.ports.logger import Logger
from domain.exceptions import VersionConflict


class TenantPreferencesRouter:
    def __init__(self, service: MealPlanService, logger: Logger) -> None:
        self._service = service
        self._logger = logger
        self.router = APIRouter(prefix="/v1/tenant-preferences", tags=["tenant-preferences"], dependencies=[Depends(inject_tenant_uri)])
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route("/", self.get_preferences, methods=["GET"], response_model=ApiResponse[TenantPreferencesSchema], status_code=200)
        self.router.add_api_route("/", self.update_preferences, methods=["PUT"], response_model=ApiResponse[TenantPreferencesSchema], status_code=200)

    async def get_preferences(self, response: Response) -> ApiResponse[TenantPreferencesSchema]:
        result = await self._service.get_tenant_preferences()
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(TenantPreferencesSchema.model_validate(result, from_attributes=True))

    async def update_preferences(
        self,
        payload: TenantPreferencesUpdateSchema,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[TenantPreferencesSchema]:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            result = await self._service.update_tenant_preferences(
                tenant_preferences_update_payload_to_domain(payload),
                expected_version,
            )
        except VersionConflict as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(TenantPreferencesSchema.model_validate(result, from_attributes=True))
