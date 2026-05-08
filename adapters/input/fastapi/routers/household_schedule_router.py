from typing import Annotated
from uuid import UUID as StdUUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from uuid6 import UUID

from adapters.input.fastapi.dependencies import inject_tenant_uri
from adapters.input.fastapi.routers.meal_plan_router import MealPlanRouter
from adapters.input.schemas.household_schedule_schema import (
    HouseholdScheduleSchema,
    HouseholdScheduleUpdateSchema,
    SchoolVacationPeriodPayload,
    SchoolVacationPeriodSchema,
    household_schedule_to_schema,
)
from application.services.meal_plan_service import MealPlanService
from arclith.adapters.input.schemas.response_wrapper import ApiResponse, success_response
from arclith.domain.ports.logger import Logger
from domain.exceptions import InvalidMealPlanOperation, SchoolVacationPeriodNotFound, VersionConflict


class HouseholdScheduleRouter:
    def __init__(self, service: MealPlanService, logger: Logger) -> None:
        self._service = service
        self._logger = logger
        self.router = APIRouter(tags=["household-schedule"], dependencies=[Depends(inject_tenant_uri)])
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route(
            "/v1/household-schedule/",
            self.get_household_schedule,
            methods=["GET"],
            response_model=ApiResponse[HouseholdScheduleSchema],
            status_code=200,
        )
        self.router.add_api_route(
            "/v1/household-schedule/",
            self.update_household_schedule,
            methods=["PUT"],
            response_model=ApiResponse[HouseholdScheduleSchema],
            status_code=200,
        )
        self.router.add_api_route(
            "/v1/school-vacation-periods/",
            self.list_school_vacation_periods,
            methods=["GET"],
            response_model=ApiResponse[list[SchoolVacationPeriodSchema]],
            status_code=200,
        )
        self.router.add_api_route(
            "/v1/school-vacation-periods/",
            self.create_school_vacation_period,
            methods=["POST"],
            response_model=ApiResponse[SchoolVacationPeriodSchema],
            status_code=201,
        )
        self.router.add_api_route(
            "/v1/school-vacation-periods/{uuid}",
            self.update_school_vacation_period,
            methods=["PUT"],
            response_model=ApiResponse[SchoolVacationPeriodSchema],
            status_code=200,
        )
        self.router.add_api_route(
            "/v1/school-vacation-periods/{uuid}",
            self.delete_school_vacation_period,
            methods=["DELETE"],
            status_code=204,
        )

    @staticmethod
    def _to_uuid6(uuid: StdUUID) -> UUID:
        return UUID(str(uuid))

    async def get_household_schedule(self, response: Response) -> ApiResponse[HouseholdScheduleSchema]:
        schedule, rules = await self._service.get_household_schedule()
        response.headers["ETag"] = MealPlanRouter._etag(schedule.version)
        return success_response(household_schedule_to_schema(schedule, rules))

    async def update_household_schedule(
        self,
        payload: HouseholdScheduleUpdateSchema,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[HouseholdScheduleSchema]:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        existing, _ = await self._service.get_household_schedule()
        try:
            schedule, rules = await self._service.update_household_schedule(
                payload.to_domain(),
                [rule.to_domain(existing.uuid, payload.schedule_mode) for rule in payload.rules],
                expected_version,
            )
        except (VersionConflict, InvalidMealPlanOperation) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = MealPlanRouter._etag(schedule.version)
        return success_response(household_schedule_to_schema(schedule, rules))

    async def list_school_vacation_periods(self) -> ApiResponse[list[SchoolVacationPeriodSchema]]:
        periods = await self._service.list_school_vacation_periods()
        return success_response([
            SchoolVacationPeriodSchema.model_validate(period, from_attributes=True)
            for period in periods
        ])

    async def create_school_vacation_period(
        self,
        payload: SchoolVacationPeriodPayload,
        response: Response,
    ) -> ApiResponse[SchoolVacationPeriodSchema]:
        result = await self._service.create_school_vacation_period(payload.to_domain())
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(SchoolVacationPeriodSchema.model_validate(result, from_attributes=True))

    async def update_school_vacation_period(
        self,
        uuid: StdUUID,
        payload: SchoolVacationPeriodPayload,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[SchoolVacationPeriodSchema]:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            result = await self._service.update_school_vacation_period(
                self._to_uuid6(uuid),
                payload.to_domain(),
                expected_version,
            )
        except (SchoolVacationPeriodNotFound, VersionConflict) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = MealPlanRouter._etag(result.version)
        return success_response(SchoolVacationPeriodSchema.model_validate(result, from_attributes=True))

    async def delete_school_vacation_period(
        self,
        uuid: StdUUID,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> None:
        expected_version = MealPlanRouter._parse_if_match(if_match)
        try:
            await self._service.delete_school_vacation_period(self._to_uuid6(uuid), expected_version)
        except (SchoolVacationPeriodNotFound, VersionConflict) as exc:
            raise self._to_http_exception(exc) from exc

    @staticmethod
    def _to_http_exception(exc: Exception) -> HTTPException:
        if isinstance(exc, SchoolVacationPeriodNotFound):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, VersionConflict):
            return HTTPException(status_code=412, detail=str(exc))
        if isinstance(exc, InvalidMealPlanOperation):
            return HTTPException(status_code=422, detail=str(exc))
        return HTTPException(status_code=500, detail="Unexpected household schedule error")
