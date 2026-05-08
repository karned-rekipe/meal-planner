from typing import Annotated
from uuid import UUID as StdUUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from uuid6 import UUID

from adapters.input.fastapi.dependencies import inject_tenant_uri
from adapters.input.fastapi.routers.meal_plan_router import MealPlanRouter
from adapters.input.schemas.household_member_schema import (
    HouseholdMemberAvatarPayload,
    HouseholdMemberPayload,
    HouseholdMemberSchema,
)
from application.services.meal_plan_service import MealPlanService
from arclith.adapters.input.schemas.response_wrapper import ApiResponse, success_response
from arclith.domain.ports.logger import Logger
from domain.exceptions import HouseholdMemberNotFound, VersionConflict


class HouseholdMemberRouter:
    def __init__(self, service: MealPlanService, logger: Logger) -> None:
        self._service = service
        self._logger = logger
        self.router = APIRouter(prefix="/v1/household-members", tags=["household-members"], dependencies=[Depends(inject_tenant_uri)])
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route(
            "/",
            self.list_household_members,
            methods=["GET"],
            response_model=ApiResponse[list[HouseholdMemberSchema]],
            status_code=200,
        )
        self.router.add_api_route(
            "/",
            self.create_household_member,
            methods=["POST"],
            response_model=ApiResponse[HouseholdMemberSchema],
            status_code=201,
        )
        self.router.add_api_route(
            "/{uuid}",
            self.update_household_member,
            methods=["PUT"],
            response_model=ApiResponse[HouseholdMemberSchema],
            status_code=200,
        )
        self.router.add_api_route(
            "/{uuid}/avatar",
            self.update_household_member_avatar,
            methods=["PUT"],
            response_model=ApiResponse[HouseholdMemberSchema],
            status_code=200,
        )
        self.router.add_api_route(
            "/{uuid}",
            self.delete_household_member,
            methods=["DELETE"],
            status_code=204,
        )

    @staticmethod
    def _to_uuid6(uuid: StdUUID) -> UUID:
        return UUID(str(uuid))

    async def list_household_members(self) -> ApiResponse[list[HouseholdMemberSchema]]:
        members = await self._service.list_household_members()
        return success_response([
            HouseholdMemberSchema.model_validate(member, from_attributes=True)
            for member in members
        ])

    async def create_household_member(
        self,
        payload: HouseholdMemberPayload,
        response: Response,
    ) -> ApiResponse[HouseholdMemberSchema]:
        result = await self._service.create_household_member(payload.to_domain())
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(HouseholdMemberSchema.model_validate(result, from_attributes=True))

    async def update_household_member(
        self,
        uuid: StdUUID,
        payload: HouseholdMemberPayload,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[HouseholdMemberSchema]:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            result = await self._service.update_household_member(
                self._to_uuid6(uuid),
                payload.to_domain(),
                expected_version,
            )
        except (HouseholdMemberNotFound, VersionConflict) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(HouseholdMemberSchema.model_validate(result, from_attributes=True))

    async def update_household_member_avatar(
        self,
        uuid: StdUUID,
        payload: HouseholdMemberAvatarPayload,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[HouseholdMemberSchema]:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            result = await self._service.update_household_member_avatar(
                self._to_uuid6(uuid),
                payload.avatar_data,
                expected_version,
            )
        except (HouseholdMemberNotFound, VersionConflict) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(HouseholdMemberSchema.model_validate(result, from_attributes=True))

    async def delete_household_member(
        self,
        uuid: StdUUID,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> None:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            await self._service.delete_household_member(self._to_uuid6(uuid), expected_version)
        except (HouseholdMemberNotFound, VersionConflict) as exc:
            raise self._to_http_exception(exc) from exc

    @staticmethod
    def _to_http_exception(exc: Exception) -> HTTPException:
        if isinstance(exc, HouseholdMemberNotFound):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, VersionConflict):
            return HTTPException(status_code=412, detail=str(exc))
        return HTTPException(status_code=500, detail="Unexpected household member error")
