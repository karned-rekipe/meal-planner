from typing import Annotated
from uuid import UUID as StdUUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from uuid6 import UUID

from adapters.input.fastapi.dependencies import inject_tenant_uri
from adapters.input.schemas.meal_plan_schema import (
    MealPlanCreateSchema,
    MealPlanPatchSchema,
    MealPlanSchema,
    MealPlanSummarySchema,
    MealPlanTransitionSchema,
    MealPlanUpdateSchema,
    RefreshRecipeSnapshotsSchema,
    meal_plan_create_payload_to_domain,
    meal_plan_to_summary,
    meal_plan_update_payload_to_domain,
)
from application.services.meal_plan_service import MealPlanService
from arclith.adapters.input.fastapi.dependencies import get_duration_ms
from arclith.adapters.input.schemas.response_wrapper import (
    ApiResponse,
    PaginatedResponse,
    ResponseMetadata,
    paginated_response,
    success_response,
)
from arclith.domain.ports.logger import Logger
from domain.exceptions import (
    IngredientNotFound,
    InvalidMealPlanOperation,
    InvalidStatusTransition,
    MealPlanNotFound,
    OverlapWithConfirmedPlan,
    RecipeNotEligible,
    RecipeNotFound,
    VersionConflict,
)
from domain.models.enums import MealPlanStatus


class MealPlanRouter:
    def __init__(self, service: MealPlanService, logger: Logger) -> None:
        self._service = service
        self._logger = logger
        self.router = APIRouter(prefix="/v1/meal-plans", tags=["meal-plans"], dependencies=[Depends(inject_tenant_uri)])
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route("/", self.create_meal_plan, methods=["POST"], response_model=ApiResponse[MealPlanSchema], status_code=201)
        self.router.add_api_route("/", self.list_meal_plans, methods=["GET"], response_model=PaginatedResponse[MealPlanSummarySchema], status_code=200)
        self.router.add_api_route("/calendar", self.get_calendar, methods=["GET"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/calendar", self.patch_calendar, methods=["PATCH"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/calendar/shopping-projection", self.calendar_shopping_projection, methods=["GET"], status_code=200)
        self.router.add_api_route("/{uuid}", self.get_meal_plan, methods=["GET"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/{uuid}", self.update_meal_plan, methods=["PUT"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/{uuid}", self.patch_meal_plan, methods=["PATCH"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/{uuid}", self.delete_meal_plan, methods=["DELETE"], status_code=204)
        self.router.add_api_route("/{uuid}/transitions", self.transition_meal_plan, methods=["POST"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/{uuid}/refresh-snapshots", self.refresh_snapshots, methods=["POST"], response_model=ApiResponse[MealPlanSchema], status_code=200)
        self.router.add_api_route("/{uuid}/shopping-projection", self.shopping_projection, methods=["GET"], status_code=200)

    @staticmethod
    def _to_uuid6(uuid: StdUUID) -> UUID:
        return UUID(str(uuid))

    async def create_meal_plan(
        self,
        payload: MealPlanCreateSchema,
        response: Response,
        request: Request,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        try:
            result = await self._service.create(meal_plan_create_payload_to_domain(payload), idempotency_key=idempotency_key)
        except (OverlapWithConfirmedPlan, RecipeNotFound, RecipeNotEligible, IngredientNotFound, InvalidMealPlanOperation) as exc:
            raise self._to_http_exception(exc) from exc
        location = f"{request.url.path.rstrip('/')}/{result.uuid}"
        response.headers["Location"] = location
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def get_meal_plan(
        self,
        uuid: StdUUID,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
    ) -> ApiResponse[MealPlanSchema]:
        result = await self._service.read(self._to_uuid6(uuid))
        if result is None:
            raise HTTPException(status_code=404, detail="MealPlan not found")
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def list_meal_plans(
        self,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        page: int = Query(1, ge=1),
        page_size: int | None = Query(None, ge=1, le=100),
        per_page: int | None = Query(None, ge=1, le=100),
        status: MealPlanStatus | None = Query(None),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
    ) -> PaginatedResponse[MealPlanSummarySchema]:
        effective_page_size = page_size or per_page or 20
        offset = (page - 1) * effective_page_size
        parsed_date_from = self._parse_optional_date(date_from, "date_from")
        parsed_date_to = self._parse_optional_date(date_to, "date_to")
        items, total = await self._service.find_page_filtered(
            status=status,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            offset=offset,
            limit=effective_page_size,
        )
        response.headers["X-Total-Count"] = str(total)
        return paginated_response(
            data=[meal_plan_to_summary(item) for item in items],
            total=total,
            page=page,
            per_page=effective_page_size,
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def get_calendar(
        self,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
    ) -> ApiResponse[MealPlanSchema]:
        parsed_date_from = self._parse_optional_date(date_from, "date_from")
        parsed_date_to = self._parse_optional_date(date_to, "date_to")
        try:
            result = await self._service.get_calendar(parsed_date_from, parsed_date_to)
        except InvalidMealPlanOperation as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def patch_calendar(
        self,
        payload: MealPlanPatchSchema,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        parsed_date_from = self._parse_optional_date(date_from, "date_from")
        parsed_date_to = self._parse_optional_date(date_to, "date_to")
        expected_version = self._parse_if_match_optional(if_match)
        try:
            result = await self._service.patch_calendar(
                [operation.to_service_operation() for operation in payload.operations],
                expected_version=expected_version,
                date_start=parsed_date_from,
                date_end=parsed_date_to,
            )
        except (VersionConflict, InvalidMealPlanOperation, RecipeNotFound, RecipeNotEligible, IngredientNotFound) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def update_meal_plan(
        self,
        uuid: StdUUID,
        payload: MealPlanUpdateSchema,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        expected_version = self._parse_if_match(if_match)
        existing = await self._service.read(self._to_uuid6(uuid))
        if existing is None:
            raise HTTPException(status_code=404, detail="MealPlan not found")
        try:
            result = await self._service.update_with_expected(
                self._to_uuid6(uuid),
                meal_plan_update_payload_to_domain(existing, payload),
                expected_version,
            )
        except (VersionConflict, OverlapWithConfirmedPlan, InvalidMealPlanOperation, RecipeNotFound, RecipeNotEligible, IngredientNotFound) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def patch_meal_plan(
        self,
        uuid: StdUUID,
        payload: MealPlanPatchSchema,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        expected_version = self._parse_if_match(if_match)
        try:
            result = await self._service.patch_slots(
                self._to_uuid6(uuid),
                [operation.to_service_operation() for operation in payload.operations],
                expected_version,
            )
        except (MealPlanNotFound, VersionConflict, InvalidMealPlanOperation, RecipeNotFound, RecipeNotEligible, IngredientNotFound) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def transition_meal_plan(
        self,
        uuid: StdUUID,
        payload: MealPlanTransitionSchema,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        expected_version = self._parse_if_match(if_match)
        try:
            result = await self._service.transition_status(self._to_uuid6(uuid), payload.target_status, expected_version)
        except (MealPlanNotFound, VersionConflict, InvalidStatusTransition, OverlapWithConfirmedPlan) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def delete_meal_plan(
        self,
        uuid: StdUUID,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> None:
        expected_version = self._parse_if_match(if_match)
        try:
            await self._service.delete_with_expected(self._to_uuid6(uuid), expected_version)
        except (MealPlanNotFound, VersionConflict, InvalidMealPlanOperation) as exc:
            raise self._to_http_exception(exc) from exc

    async def refresh_snapshots(
        self,
        uuid: StdUUID,
        payload: RefreshRecipeSnapshotsSchema,
        response: Response,
        duration_ms: Annotated[float, Depends(get_duration_ms)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> ApiResponse[MealPlanSchema]:
        expected_version = self._parse_if_match(if_match)
        try:
            result = await self._service.refresh_recipe_snapshots(self._to_uuid6(uuid), payload.items, expected_version)
        except (MealPlanNotFound, VersionConflict, InvalidMealPlanOperation, RecipeNotFound, RecipeNotEligible) as exc:
            raise self._to_http_exception(exc) from exc
        response.headers["ETag"] = self._etag(result.version)
        return success_response(
            MealPlanSchema.model_validate(result, from_attributes=True),
            metadata=ResponseMetadata(duration_ms=int(duration_ms)),
        )

    async def shopping_projection(self, uuid: StdUUID) -> dict:
        try:
            projection = await self._service.build_shopping_projection(self._to_uuid6(uuid))
        except MealPlanNotFound as exc:
            raise HTTPException(status_code=404, detail="MealPlan not found") from exc
        return {"data": projection}

    async def calendar_shopping_projection(
        self,
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
    ) -> dict:
        parsed_date_from = self._parse_optional_date(date_from, "date_from")
        parsed_date_to = self._parse_optional_date(date_to, "date_to")
        try:
            projection = await self._service.build_calendar_shopping_projection(parsed_date_from, parsed_date_to)
        except InvalidMealPlanOperation as exc:
            raise self._to_http_exception(exc) from exc
        return {"data": projection}

    @staticmethod
    def _etag(version: int) -> str:
        return f'W/"{version}"'

    @staticmethod
    def _parse_if_match(value: str | None) -> int:
        if value is None:
            raise HTTPException(status_code=412, detail="If-Match header is required")
        parsed = MealPlanRouter._parse_if_match_optional(value)
        if parsed is None:
            raise HTTPException(status_code=412, detail="Invalid If-Match header")
        return parsed

    @staticmethod
    def _parse_if_match_optional(value: str | None) -> int | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned.startswith("W/"):
            cleaned = cleaned[2:]
        cleaned = cleaned.strip('"').lstrip("vV")
        if not cleaned.isdigit():
            raise HTTPException(status_code=412, detail="Invalid If-Match header")
        return int(cleaned)

    @staticmethod
    def _parse_optional_date(value: str | None, field_name: str):
        if value is None:
            return None
        try:
            from datetime import date

            return date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{field_name} must be an ISO date") from exc

    @staticmethod
    def _to_http_exception(exc: Exception) -> HTTPException:
        if isinstance(exc, MealPlanNotFound):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, VersionConflict):
            return HTTPException(status_code=412, detail=str(exc))
        if isinstance(exc, OverlapWithConfirmedPlan):
            return HTTPException(status_code=422, detail={"message": str(exc), "conflicts": [str(item) for item in exc.conflicts]})
        if isinstance(exc, (InvalidStatusTransition, InvalidMealPlanOperation, RecipeNotFound, RecipeNotEligible, IngredientNotFound)):
            return HTTPException(status_code=422, detail=str(exc))
        return HTTPException(status_code=500, detail="Unexpected meal-planner error")
