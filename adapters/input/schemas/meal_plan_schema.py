from datetime import date, datetime
from uuid import UUID as StdUUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.services.meal_plan_service import ItemRef, MealItemInput, SlotPatchOperation
from arclith.adapters.input.schemas.base_schema import BaseSchema
from domain.models.enums import HeadcountSource, MealItemType, MealPlanStatus, SlotCode
from domain.models.meal_item import MealItem
from domain.models.meal_plan import MealPlan
from domain.models.meal_slot import MealSlot
from domain.models.recipe_preparation import RecipePreparationProgress
from domain.models.recipe_snapshot import RecipeSnapshot


def _strip_slot_code(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("slot_code cannot be empty")
    return stripped


class RecipeSnapshotIngredientSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ingredient_uuid: StdUUID
    name: str
    quantity: float
    unit: str
    season_months: list[int] = Field(default_factory=list)
    green_score: int | None = None
    rayon: str | None = None
    group: str | None = None
    supplier_uuid: StdUUID | None = None


class RecipeSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipe_uuid: StdUUID
    title: str
    short_description: str | None = None
    servings_default: int
    total_duration_min: int | None = None
    ingredients: list[RecipeSnapshotIngredientSchema] = Field(default_factory=list)
    snapshot_taken_at: datetime
    recipe_version: int | None = None


class RecipePreparationTimerSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timer_id: str
    duration_seconds: int
    remaining_seconds: int
    status: str
    started_at: datetime | None = None
    ringing_since: datetime | None = None


class RecipePreparationProgressSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_servings: int
    completed_ingredient_ids: list[str] = Field(default_factory=list)
    completed_equipment_ids: list[str] = Field(default_factory=list)
    completed_step_ids: list[str] = Field(default_factory=list)
    timers: list[RecipePreparationTimerSchema] = Field(default_factory=list)


class MealItemPayload(BaseModel):
    uuid: StdUUID | None = None
    position: int | None = Field(None, ge=0)
    item_type: MealItemType
    headcount: int | None = Field(None, ge=1, le=99)
    member_ids: list[StdUUID] = Field(default_factory=list)
    recipe_uuid: StdUUID | None = None
    recipe_snapshot: RecipeSnapshot | None = None
    preparation_progress: RecipePreparationProgress | None = None
    ingredient_uuid: StdUUID | None = None
    ingredient_name: str | None = None
    ingredient_quantity: float | None = Field(None, ge=0)
    ingredient_unit: str | None = None
    note: str | None = Field(None, max_length=500)
    legacy_id: int | None = None

    def to_service_input(self) -> MealItemInput:
        return MealItemInput.model_validate(self.model_dump())


class MealItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: StdUUID
    position: int
    item_type: MealItemType
    headcount: int | None = None
    member_ids: list[StdUUID] = Field(default_factory=list)
    recipe_uuid: StdUUID | None = None
    recipe_snapshot: RecipeSnapshotSchema | None = None
    recipe_status: str | None = None
    recipe_modified: bool = False
    preparation_progress: RecipePreparationProgressSchema | None = None
    ingredient_uuid: StdUUID | None = None
    ingredient_name: str | None = None
    ingredient_quantity: float | None = None
    ingredient_unit: str | None = None
    note: str | None = None
    legacy_id: int | None = None


class MealSlotPayload(BaseModel):
    date: date
    slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    headcount: int | None = Field(None, ge=0, le=20)
    headcount_source: HeadcountSource | None = None
    member_ids: list[StdUUID] = Field(default_factory=list)
    items: list[MealItemPayload] = Field(default_factory=list)

    @field_validator("slot_code", mode="before")
    @classmethod
    def strip_slot_code(cls, value: object) -> object:
        return _strip_slot_code(value)


class MealSlotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    slot_code: SlotCode
    headcount: int | None = None
    headcount_source: HeadcountSource | None = None
    member_ids: list[StdUUID] = Field(default_factory=list)
    items: list[MealItemSchema] = Field(default_factory=list)


class MealPlanCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    date_start: date
    date_end: date
    status: MealPlanStatus = MealPlanStatus.DRAFT
    initial_slots: list[MealSlotPayload] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Name cannot be empty")
        return value


class MealPlanUpdateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    date_start: date
    date_end: date
    status: MealPlanStatus
    slots: list[MealSlotPayload] = Field(default_factory=list)


class SlotPatchOperationSchema(BaseModel):
    op: str
    slot_date: date
    slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    headcount: int | None = Field(None, ge=0, le=20)
    member_ids: list[StdUUID] = Field(default_factory=list, max_length=20)
    item_uuid: StdUUID | None = None
    item: MealItemPayload | None = None
    new_positions: dict[StdUUID, int] | None = None
    preparation_progress: RecipePreparationProgress | None = None

    @field_validator("slot_code", mode="before")
    @classmethod
    def strip_slot_code(cls, value: object) -> object:
        return _strip_slot_code(value)

    def to_service_operation(self) -> SlotPatchOperation:
        payload = self.model_dump()
        if self.item is not None:
            payload["item"] = self.item.to_service_input()
        return SlotPatchOperation.model_validate(payload)


class MealPlanPatchSchema(BaseModel):
    operations: list[SlotPatchOperationSchema] = Field(default_factory=list)


class MealPlanTransitionSchema(BaseModel):
    target_status: MealPlanStatus


class RefreshRecipeSnapshotsSchema(BaseModel):
    items: list[ItemRef] = Field(default_factory=list)


class MealPlanCreatedSchema(BaseModel):
    uuid: StdUUID


class MealPlanSchema(BaseSchema):
    name: str
    status: MealPlanStatus
    date_start: date
    date_end: date
    slots: list[MealSlotSchema] = Field(default_factory=list)
    migration_metadata: dict[str, str | int | float | bool | None] | None = None


class MealPlanSummarySchema(BaseModel):
    uuid: StdUUID
    name: str
    status: MealPlanStatus
    date_start: date
    date_end: date
    items_count: int
    headcount_avg: float | None
    version: int


def meal_plan_create_payload_to_domain(payload: MealPlanCreateSchema) -> MealPlan:
    return MealPlan(
        name=payload.name,
        status=payload.status,
        date_start=payload.date_start,
        date_end=payload.date_end,
        slots=_slots_to_domain(payload.initial_slots or []),
    )


def meal_plan_update_payload_to_domain(existing: MealPlan, payload: MealPlanUpdateSchema) -> MealPlan:
    return MealPlan(
        uuid=existing.uuid,
        name=payload.name,
        status=payload.status,
        date_start=payload.date_start,
        date_end=payload.date_end,
        slots=_slots_to_domain(payload.slots),
        created_at=existing.created_at,
        created_by=existing.created_by,
        updated_at=existing.updated_at,
        updated_by=existing.updated_by,
        version=existing.version,
        migration_metadata=existing.migration_metadata,
    )


def meal_plan_to_summary(plan: MealPlan) -> MealPlanSummarySchema:
    items_count = sum(len(slot.items) for slot in plan.slots)
    headcounts = [slot.headcount for slot in plan.slots if slot.headcount is not None]
    headcount_avg = round(sum(headcounts) / len(headcounts), 2) if headcounts else None
    return MealPlanSummarySchema(
        uuid=plan.uuid,
        name=plan.name,
        status=plan.status,
        date_start=plan.date_start,
        date_end=plan.date_end,
        items_count=items_count,
        headcount_avg=headcount_avg,
        version=plan.version,
    )


def _slots_to_domain(payloads: list[MealSlotPayload]) -> list[MealSlot]:
    return [
        MealSlot(
            date=payload.date,
            slot_code=payload.slot_code,
            headcount=payload.headcount,
            headcount_source=payload.headcount_source or (HeadcountSource.MANUAL if payload.headcount is not None else None),
            member_ids=payload.member_ids,
            items=[_item_payload_to_domain(item) for item in payload.items],
        )
        for payload in payloads
    ]


def _item_payload_to_domain(payload: MealItemPayload) -> MealItem:
    data = payload.model_dump(exclude_none=True)
    if "position" not in data:
        data["position"] = 0
    return MealItem.model_validate(data)
