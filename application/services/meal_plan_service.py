import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from uuid6 import UUID as UUID7

from arclith import BaseService, Logger
from domain.exceptions import (
    HouseholdMemberNotFound,
    IngredientNotFound,
    InvalidMealPlanOperation,
    InvalidStatusTransition,
    MealPlanNotFound,
    OverlapWithConfirmedPlan,
    SchoolVacationCalendarUnavailable,
    SchoolVacationPeriodNotFound,
    VersionConflict,
)
from domain.models.enums import (
    DayOfWeek,
    HeadcountSource,
    MealItemType,
    MealPlanStatus,
    ScheduleMode,
    SchoolPeriodType,
    SchoolZone,
    SlotCode,
    VacationPeriodSource,
    WeekParity,
)
from domain.models.household_member import HouseholdMember
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.models.ingredient_snapshot import IngredientSnapshot
from domain.models.legacy_meal_plan_entry import LegacyMealPlanEntry
from domain.models.meal_item import MealItem
from domain.models.meal_plan import MealPlan
from domain.models.meal_slot import MealSlot
from domain.models.recipe_snapshot import RecipeSnapshot
from domain.models.school_vacation_period import SchoolVacationPeriod
from domain.models.tenant_preferences import TenantPreferences
from domain.ports.output.household_schedule_repository import HouseholdScheduleRepository
from domain.ports.output.household_member_repository import HouseholdMemberRepository
from domain.ports.output.meal_plan_repository import MealPlanRepository
from domain.ports.output.recipe_client import RecipeClient
from domain.ports.output.school_vacation_calendar_client import SchoolVacationCalendarClient
from domain.ports.output.school_vacation_period_repository import SchoolVacationPeriodRepository
from domain.ports.output.tenant_preferences_repository import TenantPreferencesRepository

PERPETUAL_CALENDAR_KIND = "perpetual_calendar"
PERPETUAL_CALENDAR_NAME = "Planning perpétuel"
DEFAULT_CALENDAR_DAYS = 15
SLOT_CREATING_OPERATIONS = {"set_headcount", "set_members", "add_item"}
LEGACY_LUNCH_SLOT_CODES = {"1", "lunch", "midi", "dej", "dejeuner", "déjeuner"}
LEGACY_DINNER_SLOT_CODES = {"3", "dinner", "soir", "diner", "dîner"}
DAY_OF_WEEK_BY_INDEX: tuple[DayOfWeek, ...] = (
    DayOfWeek.MONDAY,
    DayOfWeek.TUESDAY,
    DayOfWeek.WEDNESDAY,
    DayOfWeek.THURSDAY,
    DayOfWeek.FRIDAY,
    DayOfWeek.SATURDAY,
    DayOfWeek.SUNDAY,
)


def _repository_uuid(value: UUID) -> UUID7:
    return UUID7(str(value))


def _strip_slot_code(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("slot_code cannot be empty")
    return stripped


class MealItemInput(BaseModel):
    uuid: UUID | None = None
    position: int | None = Field(None, ge=0)
    item_type: MealItemType
    headcount: int | None = Field(None, ge=1, le=99)
    member_ids: list[UUID] = Field(default_factory=list)
    recipe_uuid: UUID | None = None
    recipe_snapshot: RecipeSnapshot | None = None
    ingredient_uuid: UUID | None = None
    ingredient_name: str | None = None
    ingredient_quantity: float | None = Field(None, ge=0)
    ingredient_unit: str | None = None
    note: str | None = Field(None, max_length=500)
    legacy_id: int | None = None


class SlotPatchOperation(BaseModel):
    op: Literal["set_headcount", "set_members", "add_item", "update_item", "remove_item", "reorder_items"]
    slot_date: date
    slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    headcount: int | None = Field(None, ge=0, le=20)
    member_ids: list[UUID] = Field(default_factory=list, max_length=20)
    item_uuid: UUID | None = None
    item: MealItemInput | None = None
    new_positions: dict[UUID, int] | None = None

    @field_validator("slot_code", mode="before")
    @classmethod
    def strip_slot_code(cls, value: object) -> object:
        return _strip_slot_code(value)


class ItemRef(BaseModel):
    slot_date: date
    slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    item_uuid: UUID

    @field_validator("slot_code", mode="before")
    @classmethod
    def strip_slot_code(cls, value: object) -> object:
        return _strip_slot_code(value)


class MealPlanService(BaseService[MealPlan]):
    def __init__(
        self,
        repository: MealPlanRepository,
        logger: Logger,
        retention_days: float | None = None,
        recipe_client: RecipeClient | None = None,
        tenant_preferences_repository: TenantPreferencesRepository | None = None,
        household_schedule_repository: HouseholdScheduleRepository | None = None,
        household_member_repository: HouseholdMemberRepository | None = None,
        school_vacation_period_repository: SchoolVacationPeriodRepository | None = None,
        school_vacation_calendar_client: SchoolVacationCalendarClient | None = None,
    ) -> None:
        super().__init__(repository, logger, retention_days)
        self._meal_plan_repo = repository
        self._recipe_client = recipe_client
        self._tenant_preferences_repo = tenant_preferences_repository
        self._household_schedule_repo = household_schedule_repository
        self._household_member_repo = household_member_repository
        self._school_vacation_period_repo = school_vacation_period_repository
        self._school_vacation_calendar_client = school_vacation_calendar_client
        self._idempotency_cache: dict[str, MealPlan] = {}

    async def create(self, entity: MealPlan, idempotency_key: str | None = None) -> MealPlan:
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return self._idempotency_cache[idempotency_key]
        completed = await self._complete_plan_slots(entity)
        plan = await self._prepare_for_save(completed)
        if plan.status == MealPlanStatus.CONFIRMED:
            await self._assert_no_confirmed_overlap(plan.date_start, plan.date_end)
        created = await super().create(plan)
        if idempotency_key:
            self._idempotency_cache[idempotency_key] = created
        return created

    async def read(self, uuid: UUID) -> MealPlan | None:
        plan = await super().read(_repository_uuid(uuid))
        if plan is None:
            return None
        return await self._enrich_recipe_status(plan)

    async def update(self, entity: MealPlan) -> MealPlan:
        return await self.update_with_expected(entity.uuid, entity, entity.version)

    async def update_with_expected(self, uuid: UUID, payload: MealPlan, expected_version: int) -> MealPlan:
        existing = await self._get_existing(uuid)
        self._assert_version(existing, expected_version)
        plan = payload.model_copy(
            update={
                "uuid": existing.uuid,
                "created_at": existing.created_at,
                "created_by": existing.created_by,
                "migration_metadata": existing.migration_metadata,
                "version": existing.version,
            },
        )
        completed = await self._complete_plan_slots(plan)
        plan = await self._prepare_for_save(completed)
        if plan.status == MealPlanStatus.CONFIRMED:
            await self._assert_no_confirmed_overlap(plan.date_start, plan.date_end, exclude_uuid=plan.uuid)
        updated = plan.model_copy(
            update={
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        return await self._meal_plan_repo.update(updated)

    async def patch_slots(
        self,
        uuid: UUID,
        operations: list[SlotPatchOperation],
        expected_version: int,
    ) -> MealPlan:
        existing = await self._get_existing(uuid)
        self._assert_version(existing, expected_version)
        self._assert_mutable(existing)
        slot_codes = await self._meal_slot_codes()
        slots = [slot.model_copy(deep=True) for slot in existing.slots]
        for operation in operations:
            if operation.op in SLOT_CREATING_OPERATIONS:
                self._assert_slot_date_inside_plan(existing, operation.slot_date)
                slot_index = self._find_slot_index_or_none(slots, operation.slot_date, operation.slot_code)
                if slot_index is None:
                    self._assert_global_slot_code(operation.slot_code, slot_codes)
                    slot_index = self._append_slot(slots, operation.slot_date, operation.slot_code)
            else:
                slot_index = self._find_slot_index(slots, operation.slot_date, operation.slot_code)
            slots = await self._apply_slot_operation(slots, slot_index, operation)

        updated = existing.model_copy(
            update={
                "slots": slots,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        updated = await self._complete_plan_slots(updated)
        return await self._meal_plan_repo.update(updated)

    async def transition_status(
        self,
        uuid: UUID,
        target_status: MealPlanStatus,
        expected_version: int,
    ) -> MealPlan:
        existing = await self._get_existing(uuid)
        self._assert_version(existing, expected_version)
        allowed = {
            MealPlanStatus.DRAFT: {MealPlanStatus.CONFIRMED, MealPlanStatus.ABANDONED},
            MealPlanStatus.CONFIRMED: {MealPlanStatus.DONE, MealPlanStatus.ABANDONED},
            MealPlanStatus.DONE: set(),
            MealPlanStatus.ABANDONED: set(),
        }
        if target_status not in allowed[existing.status]:
            raise InvalidStatusTransition(f"{existing.status.value} -> {target_status.value} is not allowed")
        if target_status == MealPlanStatus.CONFIRMED:
            await self._assert_no_confirmed_overlap(existing.date_start, existing.date_end, exclude_uuid=existing.uuid)
        updated = existing.model_copy(
            update={
                "status": target_status,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        return await self._meal_plan_repo.update(updated)

    async def delete_with_expected(self, uuid: UUID, expected_version: int) -> None:
        existing = await self._get_existing(uuid)
        self._assert_version(existing, expected_version)
        if existing.status not in (MealPlanStatus.DRAFT, MealPlanStatus.ABANDONED):
            raise InvalidMealPlanOperation("Only draft or abandoned meal plans can be deleted")
        await self._meal_plan_repo.delete(_repository_uuid(uuid))

    async def delete(self, uuid: UUID, deleted_by: str | None = None) -> None:
        existing = await self._get_existing(uuid)
        await self.delete_with_expected(uuid, existing.version)

    async def refresh_recipe_snapshots(
        self,
        uuid: UUID,
        refs: list[ItemRef],
        expected_version: int,
    ) -> MealPlan:
        existing = await self._get_existing(uuid)
        self._assert_version(existing, expected_version)
        self._assert_mutable(existing)
        slots = [slot.model_copy(deep=True) for slot in existing.slots]
        for ref in refs:
            slot_index = self._find_slot_index(slots, ref.slot_date, ref.slot_code)
            slot = slots[slot_index]
            new_items: list[MealItem] = []
            for item in slot.items:
                if item.uuid == ref.item_uuid and item.item_type == MealItemType.RECIPE and item.recipe_uuid is not None:
                    snapshot = await self._get_recipe_snapshot(item.recipe_uuid)
                    new_items.append(item.model_copy(update={"recipe_snapshot": snapshot, "recipe_status": None, "recipe_modified": False}))
                else:
                    new_items.append(item)
            slots[slot_index] = slot.model_copy(update={"items": new_items})
        updated = existing.model_copy(
            update={
                "slots": slots,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        return await self._meal_plan_repo.update(updated)

    async def find_page_filtered(
        self,
        *,
        status: MealPlanStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[MealPlan], int]:
        return await self._meal_plan_repo.find_page_filtered(
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )

    async def find_by_name(self, name: str) -> list[MealPlan]:
        return await self._meal_plan_repo.find_by_name(name)

    async def find_recent_recipe_uuids(self, days: int = 30) -> set[UUID]:
        return await self._meal_plan_repo.find_recent_recipe_uuids(date.today() - timedelta(days=days))

    async def get_calendar(
        self,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> MealPlan:
        range_start, range_end = self._resolve_calendar_range(date_start, date_end)
        plan = await self._get_or_create_perpetual_plan(range_start, range_end)
        projected = await self._project_plan_to_range(plan, range_start, range_end)
        return projected

    async def patch_calendar(
        self,
        operations: list[SlotPatchOperation],
        *,
        expected_version: int | None = None,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> MealPlan:
        if not operations:
            return await self.get_calendar(date_start, date_end)

        operation_dates = [operation.slot_date for operation in operations]
        range_start, range_end = self._resolve_calendar_range(
            date_start or min(operation_dates),
            date_end or max(operation_dates),
        )
        existing = await self._get_or_create_perpetual_plan(range_start, range_end)
        # Perpetual calendar edits are operation-scoped. A global ETag would
        # reject independent cell edits after any other calendar change.
        _ = expected_version
        self._assert_mutable(existing)

        slot_codes = await self._meal_slot_codes()
        slots = [slot.model_copy(deep=True) for slot in existing.slots]
        for operation in operations:
            if operation.op in SLOT_CREATING_OPERATIONS:
                slot_index = self._find_slot_index_or_none(slots, operation.slot_date, operation.slot_code)
                if slot_index is None:
                    self._assert_global_slot_code(operation.slot_code, slot_codes)
                    slot_index = self._append_slot(slots, operation.slot_date, operation.slot_code)
            else:
                slot_index = self._find_slot_index(slots, operation.slot_date, operation.slot_code)
            slots = await self._apply_slot_operation(slots, slot_index, operation)

        persisted_slots = self._persistable_calendar_slots(slots)
        storage_start, storage_end = self._calendar_storage_bounds(
            persisted_slots,
            fallback_start=range_start,
            fallback_end=range_end,
        )
        updated = existing.model_copy(
            update={
                "date_start": storage_start,
                "date_end": storage_end,
                "slots": persisted_slots,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        persisted = await self._meal_plan_repo.update(updated)
        projected = await self._project_plan_to_range(persisted, range_start, range_end)
        return projected

    async def get_tenant_preferences(self) -> TenantPreferences:
        if self._tenant_preferences_repo is None:
            return TenantPreferences()
        preferences = await self._tenant_preferences_repo.get_singleton()
        if preferences is not None:
            return preferences
        return await self._tenant_preferences_repo.save_singleton(TenantPreferences())

    async def update_tenant_preferences(
        self,
        preferences: TenantPreferences,
        expected_version: int,
    ) -> TenantPreferences:
        existing = await self.get_tenant_preferences()
        self._assert_version(existing, expected_version)
        updated = preferences.model_copy(
            update={
                "uuid": existing.uuid,
                "created_at": existing.created_at,
                "created_by": existing.created_by,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._tenant_preferences_repo is None:
            return updated
        return await self._tenant_preferences_repo.save_singleton(updated)

    async def get_household_schedule(self) -> tuple[HouseholdSchedule, list[HouseholdScheduleRule]]:
        if self._household_schedule_repo is None:
            return HouseholdSchedule(), []
        schedule = await self._household_schedule_repo.get_singleton()
        if schedule is None:
            schedule = await self._household_schedule_repo.save_singleton(HouseholdSchedule())
        elif schedule.schedule_mode != ScheduleMode.MEMBERS:
            schedule = schedule.model_copy(update={"schedule_mode": ScheduleMode.MEMBERS})
        rules = await self._household_schedule_repo.list_rules(schedule.uuid)
        return schedule, rules

    async def update_household_schedule(
        self,
        schedule: HouseholdSchedule,
        rules: list[HouseholdScheduleRule],
        expected_version: int,
    ) -> tuple[HouseholdSchedule, list[HouseholdScheduleRule]]:
        existing, _ = await self.get_household_schedule()
        self._assert_version(existing, expected_version)
        await self._assert_household_schedule_rules_are_valid(rules)
        updated = schedule.model_copy(
            update={
                "uuid": existing.uuid,
                "created_at": existing.created_at,
                "created_by": existing.created_by,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        normalized_rules = await self._normalize_household_schedule_rules(existing.uuid, rules)
        if self._household_schedule_repo is None:
            return updated, normalized_rules
        saved_schedule = await self._household_schedule_repo.save_singleton(updated)
        saved_rules = await self._household_schedule_repo.replace_rules(saved_schedule.uuid, normalized_rules)
        return saved_schedule, saved_rules

    async def update_household_school_zone(
        self,
        school_zone: SchoolZone | None,
        expected_version: int,
    ) -> HouseholdSchedule:
        existing, _ = await self.get_household_schedule()
        self._assert_version(existing, expected_version)
        updated = existing.model_copy(
            update={
                "school_zone": school_zone,
                "schedule_mode": ScheduleMode.MEMBERS,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._household_schedule_repo is None:
            return updated
        return await self._household_schedule_repo.save_singleton(updated)

    async def list_household_members(self) -> list[HouseholdMember]:
        if self._household_member_repo is None:
            return []
        return await self._household_member_repo.list_all()

    async def create_household_member(self, member: HouseholdMember) -> HouseholdMember:
        if self._household_member_repo is None:
            return member
        return await self._household_member_repo.save(member)

    async def update_household_member(
        self,
        uuid: UUID,
        member: HouseholdMember,
        expected_version: int,
    ) -> HouseholdMember:
        existing = await self._get_existing_household_member(uuid)
        self._assert_version(existing, expected_version)
        updated = member.model_copy(
            update={
                "uuid": existing.uuid,
                "created_at": existing.created_at,
                "created_by": existing.created_by,
                "avatar_data": existing.avatar_data,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._household_member_repo is None:
            return updated
        return await self._household_member_repo.save(updated)

    async def update_household_member_avatar(
        self,
        uuid: UUID,
        avatar_data: str,
        expected_version: int,
    ) -> HouseholdMember:
        existing = await self._get_existing_household_member(uuid)
        self._assert_version(existing, expected_version)
        updated = existing.model_copy(
            update={
                "avatar_data": avatar_data,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._household_member_repo is None:
            return updated
        return await self._household_member_repo.save(updated)

    async def delete_household_member(self, uuid: UUID, expected_version: int) -> None:
        existing = await self._get_existing_household_member(uuid)
        self._assert_version(existing, expected_version)
        if self._household_member_repo is not None:
            await self._household_member_repo.delete(uuid)

    async def list_school_vacation_periods(self) -> list[SchoolVacationPeriod]:
        if self._school_vacation_period_repo is None:
            return []
        periods = [period for period in await self._school_vacation_period_repo.find_all() if not period.is_deleted]
        periods.sort(key=lambda period: (period.start_date, period.end_date, period.name))
        return periods

    async def create_school_vacation_period(self, period: SchoolVacationPeriod) -> SchoolVacationPeriod:
        if self._school_vacation_period_repo is None:
            return period
        return await self._school_vacation_period_repo.create(period)

    async def update_school_vacation_period(
        self,
        uuid: UUID,
        period: SchoolVacationPeriod,
        expected_version: int,
    ) -> SchoolVacationPeriod:
        existing = await self._get_existing_school_vacation_period(uuid)
        self._assert_version(existing, expected_version)
        updated = period.model_copy(
            update={
                "uuid": existing.uuid,
                "created_at": existing.created_at,
                "created_by": existing.created_by,
                "version": existing.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._school_vacation_period_repo is None:
            return updated
        return await self._school_vacation_period_repo.update(updated)

    async def delete_school_vacation_period(self, uuid: UUID, expected_version: int) -> None:
        existing = await self._get_existing_school_vacation_period(uuid)
        self._assert_version(existing, expected_version)
        if self._school_vacation_period_repo is None:
            return
        await self._school_vacation_period_repo.delete(_repository_uuid(uuid))

    async def sync_official_school_vacation_periods(
        self,
        school_zone: SchoolZone | None = None,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> tuple[SchoolZone, date, date, int, int, int, list[SchoolVacationPeriod]]:
        schedule, _ = await self.get_household_schedule()
        resolved_zone, range_start, range_end = self._resolve_official_calendar_request(
            school_zone or schedule.school_zone,
            date_start,
            date_end,
        )
        incoming = await self._fetch_official_school_vacation_periods(resolved_zone, range_start, range_end)
        if self._school_vacation_period_repo is None:
            return resolved_zone, range_start, range_end, len(incoming), 0, 0, incoming

        existing = await self._list_official_school_vacation_periods(resolved_zone, range_start, range_end)
        created_count, updated_count, stale_periods, synced_periods = (
            await self._reconcile_official_school_vacation_periods(incoming, existing)
        )
        return (
            resolved_zone,
            range_start,
            range_end,
            created_count,
            updated_count,
            len(stale_periods),
            synced_periods,
        )

    @staticmethod
    def _resolve_official_calendar_request(
        school_zone: SchoolZone | None,
        date_start: date | None,
        date_end: date | None,
    ) -> tuple[SchoolZone, date, date]:
        if school_zone is None:
            raise InvalidMealPlanOperation("Une zone scolaire doit être définie avant de récupérer le calendrier officiel.")
        range_start = date_start or date(date.today().year, 1, 1)
        range_end = date_end or date(date.today().year + 2, 12, 31)
        if range_end < range_start:
            raise InvalidMealPlanOperation("date_end must be greater than or equal to date_start")
        return school_zone, range_start, range_end

    async def _fetch_official_school_vacation_periods(
        self,
        school_zone: SchoolZone,
        date_start: date,
        date_end: date,
    ) -> list[SchoolVacationPeriod]:
        if self._school_vacation_calendar_client is None:
            raise InvalidMealPlanOperation("Le client du calendrier officiel n'est pas configuré.")
        periods = await self._school_vacation_calendar_client.fetch_periods(school_zone, date_start, date_end)
        if not periods:
            raise SchoolVacationCalendarUnavailable(
                "Le calendrier officiel n'a retourné aucune période pour la zone et les dates demandées."
            )
        return periods

    async def _list_official_school_vacation_periods(
        self,
        school_zone: SchoolZone,
        date_start: date,
        date_end: date,
    ) -> list[SchoolVacationPeriod]:
        if self._school_vacation_period_repo is None:
            return []
        return [
            period
            for period in await self._school_vacation_period_repo.find_all()
            if not period.is_deleted
            and period.source == VacationPeriodSource.OFFICIAL
            and period.school_zone == school_zone
            and period.end_date >= date_start
            and period.start_date <= date_end
        ]

    async def _reconcile_official_school_vacation_periods(
        self,
        incoming: list[SchoolVacationPeriod],
        existing: list[SchoolVacationPeriod],
    ) -> tuple[int, int, list[SchoolVacationPeriod], list[SchoolVacationPeriod]]:
        remaining_by_name: dict[str, list[SchoolVacationPeriod]] = {}
        for period in existing:
            remaining_by_name.setdefault(period.name, []).append(period)

        created_count = 0
        updated_count = 0
        synced_periods: list[SchoolVacationPeriod] = []
        matched_uuids: set[UUID] = set()
        for period in incoming:
            synced, was_created, was_updated = await self._upsert_official_school_vacation_period(
                period,
                remaining_by_name.get(period.name, []),
                matched_uuids,
            )
            synced_periods.append(synced)
            matched_uuids.add(synced.uuid)
            created_count += int(was_created)
            updated_count += int(was_updated)

        stale_periods = [period for period in existing if period.uuid not in matched_uuids]
        if self._school_vacation_period_repo is not None:
            for period in stale_periods:
                await self._school_vacation_period_repo.delete(period.uuid)

        synced_periods.sort(key=lambda period: (period.start_date, period.end_date, period.name))
        return created_count, updated_count, stale_periods, synced_periods

    async def _upsert_official_school_vacation_period(
        self,
        incoming: SchoolVacationPeriod,
        candidates: list[SchoolVacationPeriod],
        matched_uuids: set[UUID],
    ) -> tuple[SchoolVacationPeriod, bool, bool]:
        exact = next(
            (
                candidate
                for candidate in candidates
                if candidate.start_date == incoming.start_date and candidate.end_date == incoming.end_date
            ),
            None,
        )
        if exact is not None:
            return exact, False, False

        candidate = next((item for item in candidates if item.uuid not in matched_uuids), None)
        if candidate is None:
            if self._school_vacation_period_repo is None:
                return incoming, True, False
            return await self._school_vacation_period_repo.create(incoming), True, False

        updated = incoming.model_copy(
            update={
                "uuid": candidate.uuid,
                "created_at": candidate.created_at,
                "created_by": candidate.created_by,
                "version": candidate.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if self._school_vacation_period_repo is None:
            return updated, False, True
        return await self._school_vacation_period_repo.update(updated), False, True

    async def build_shopping_projection(self, uuid: UUID) -> dict:
        plan = await self._get_existing(uuid)
        return self._build_projection_for_plan(plan)

    async def build_calendar_shopping_projection(
        self,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> dict:
        range_start, range_end = self._resolve_calendar_range(date_start, date_end)
        plan = await self._get_or_create_perpetual_plan(range_start, range_end)
        projected = await self._project_plan_to_range(
            plan,
            range_start,
            range_end,
            hydrate_legacy_recipes=True,
        )
        return self._build_projection_for_plan(projected)

    def _build_projection_for_plan(self, plan: MealPlan) -> dict:
        generated_at = datetime.now(timezone.utc).isoformat()
        grouped: dict[tuple[str, str], dict] = {}
        warnings: list[dict] = []
        units_by_ingredient: dict[str, set[str]] = {}

        for slot in plan.slots:
            for item in slot.items:
                if item.item_type == MealItemType.RECIPE and item.recipe_snapshot is not None:
                    headcount = self._item_headcount(item, slot.headcount, item.recipe_snapshot.servings_default)
                    scale_factor = headcount / item.recipe_snapshot.servings_default
                    for ingredient in item.recipe_snapshot.ingredients:
                        key = (str(ingredient.ingredient_uuid), ingredient.unit)
                        units_by_ingredient.setdefault(key[0], set()).add(ingredient.unit)
                        entry = grouped.setdefault(
                            key,
                            {
                                "ingredient_uuid": str(ingredient.ingredient_uuid),
                                "name": ingredient.name,
                                "group": ingredient.group,
                                "rayon": ingredient.rayon,
                                "supplier_uuid": str(ingredient.supplier_uuid) if ingredient.supplier_uuid is not None else None,
                                "season_months": ingredient.season_months,
                                "lines": [],
                                "aggregated": {"quantity": 0.0, "unit": ingredient.unit},
                            },
                        )
                        scaled_quantity = ingredient.quantity * scale_factor
                        entry["lines"].append(
                            {
                                "source_type": "recipe",
                                "source_uuid": str(item.uuid),
                                "slot_date": slot.date.isoformat(),
                                "slot_code": slot.slot_code,
                                "scaled_quantity": scaled_quantity,
                                "unit": ingredient.unit,
                                "scale_factor": scale_factor,
                                "headcount": headcount,
                            },
                        )
                        entry["aggregated"]["quantity"] += scaled_quantity
                elif item.item_type == MealItemType.INGREDIENT and item.ingredient_uuid is not None and item.ingredient_unit:
                    headcount = self._item_headcount(item, slot.headcount, 1)
                    key = (str(item.ingredient_uuid), item.ingredient_unit)
                    units_by_ingredient.setdefault(key[0], set()).add(item.ingredient_unit)
                    entry = grouped.setdefault(
                        key,
                        {
                            "ingredient_uuid": str(item.ingredient_uuid),
                            "name": item.ingredient_name,
                            "group": None,
                            "rayon": None,
                            "supplier_uuid": None,
                            "season_months": [],
                            "lines": [],
                            "aggregated": {"quantity": 0.0, "unit": item.ingredient_unit},
                        },
                    )
                    quantity = (item.ingredient_quantity or 0) * headcount
                    entry["lines"].append(
                        {
                            "source_type": "ingredient",
                            "source_uuid": str(item.uuid),
                            "slot_date": slot.date.isoformat(),
                            "slot_code": slot.slot_code,
                            "scaled_quantity": quantity,
                            "unit": item.ingredient_unit,
                            "scale_factor": headcount,
                            "headcount": headcount,
                        },
                    )
                    entry["aggregated"]["quantity"] += quantity

        for ingredient_uuid, units in units_by_ingredient.items():
            if len(units) > 1:
                warnings.append(
                    {
                        "code": "unit_mismatch",
                        "ingredient_uuid": ingredient_uuid,
                        "details": " vs ".join(sorted(units)),
                    },
                )

        headcount_days = sum(self._slot_projection_headcount(slot) for slot in plan.slots)
        groups = {item["group"] for item in grouped.values() if item.get("group")}
        return {
            "meal_plan_uuid": str(plan.uuid),
            "period": {"start": plan.date_start.isoformat(), "end": plan.date_end.isoformat()},
            "generated_at": generated_at,
            "totals": {
                "headcount_days": headcount_days,
                "ingredients_count": len(grouped),
                "groups_count": len(groups),
            },
            "ingredients": list(grouped.values()),
            "warnings": warnings,
        }

    async def _get_or_create_perpetual_plan(self, date_start: date, date_end: date) -> MealPlan:
        existing = await self._find_perpetual_plan()
        if existing is not None:
            return existing
        plan = MealPlan(
            name=PERPETUAL_CALENDAR_NAME,
            status=MealPlanStatus.DRAFT,
            date_start=date_start,
            date_end=date_end,
            slots=[],
            migration_metadata={"kind": PERPETUAL_CALENDAR_KIND},
        )
        return await super().create(await self._complete_plan_slots(plan))

    async def _find_perpetual_plan(self) -> MealPlan | None:
        for plan in await self._meal_plan_repo.find_all():
            metadata = plan.migration_metadata or {}
            if not plan.is_deleted and metadata.get("kind") == PERPETUAL_CALENDAR_KIND:
                return plan
        return None

    @staticmethod
    def _resolve_calendar_range(date_start: date | None, date_end: date | None) -> tuple[date, date]:
        start = date_start or date.today()
        end = date_end or (start + timedelta(days=DEFAULT_CALENDAR_DAYS - 1))
        if end < start:
            raise InvalidMealPlanOperation("date_to must be greater than or equal to date_from")
        return start, end

    async def _project_plan_to_range(
        self,
        plan: MealPlan,
        date_start: date,
        date_end: date,
        *,
        hydrate_legacy_recipes: bool = False,
    ) -> MealPlan:
        slot_codes = await self._meal_slot_codes()
        slots = MealPlan._complete_slots_for_period(plan.slots, date_start, date_end, slot_codes)
        projected = plan.model_copy(update={"date_start": date_start, "date_end": date_end, "slots": slots})
        projected = await self._apply_household_schedule(projected)
        return await self._with_legacy_entries(projected, hydrate_recipe_snapshots=hydrate_legacy_recipes)

    async def _complete_plan_slots(self, plan: MealPlan) -> MealPlan:
        slot_codes = await self._meal_slot_codes()
        slots = MealPlan._complete_slots_for_period(plan.slots, plan.date_start, plan.date_end, slot_codes)
        completed = plan.model_copy(update={"slots": slots})
        return await self._apply_household_schedule(completed)

    def _persistable_calendar_slots(self, slots: list[MealSlot]) -> list[MealSlot]:
        persisted: list[MealSlot] = []
        for slot in slots:
            items = self._renumber(slot.items)
            has_manual_headcount = (
                slot.headcount_source == HeadcountSource.MANUAL
                or (slot.headcount is not None and slot.headcount_source != HeadcountSource.HOUSEHOLD_SCHEDULE)
            )
            if not items and not has_manual_headcount:
                continue

            updates: dict[str, object] = {"items": items}
            if slot.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE:
                updates["headcount"] = None
                updates["headcount_source"] = None
                updates["member_ids"] = []
            elif has_manual_headcount and slot.headcount_source is None:
                updates["headcount_source"] = HeadcountSource.MANUAL
            persisted.append(slot.model_copy(update=updates))
        return persisted

    @staticmethod
    def _calendar_storage_bounds(
        slots: list[MealSlot],
        *,
        fallback_start: date,
        fallback_end: date,
    ) -> tuple[date, date]:
        if not slots:
            return fallback_start, fallback_end
        dates = [slot.date for slot in slots]
        return min(dates), max(dates)

    async def _meal_slot_codes(self) -> tuple[SlotCode, ...]:
        preferences = await self.get_tenant_preferences()
        return tuple(slot.code for slot in sorted(preferences.meal_slots, key=lambda item: item.position))

    async def _apply_household_schedule(self, plan: MealPlan) -> MealPlan:
        if self._household_schedule_repo is None:
            return plan
        schedule = await self._household_schedule_repo.get_singleton()
        if schedule is None:
            return plan
        rules = await self._household_schedule_repo.list_rules(schedule.uuid)
        if not rules:
            return plan

        active_member_ids = await self._active_household_member_ids()
        rule_by_key = {
            (rule.week_parity, rule.school_period_type, rule.day_of_week, rule.meal_slot_code): rule
            for rule in rules
        }
        period_types_by_date: dict[date, SchoolPeriodType] = {}
        slots: list[MealSlot] = []
        for slot in plan.slots:
            if slot.headcount is not None or slot.headcount_source is not None:
                slots.append(slot)
                continue

            school_period_type = period_types_by_date.get(slot.date)
            if school_period_type is None:
                school_period_type = await self._school_period_type(slot.date, schedule.school_zone)
                period_types_by_date[slot.date] = school_period_type

            rule = rule_by_key.get(
                (
                    self._week_parity(slot.date),
                    school_period_type,
                    DAY_OF_WEEK_BY_INDEX[slot.date.weekday()],
                    slot.slot_code,
                ),
            )
            if rule is None:
                slots.append(slot)
                continue
            member_ids = [
                member_id
                for member_id in rule.member_ids
                if active_member_ids is None or member_id in active_member_ids
            ]
            headcount = len(member_ids)
            slots.append(
                slot.model_copy(
                    update={
                        "headcount": headcount,
                        "headcount_source": HeadcountSource.HOUSEHOLD_SCHEDULE,
                        "member_ids": member_ids,
                    },
                ),
            )
        return plan.model_copy(update={"slots": slots})

    async def _school_period_type(
        self,
        target_date: date,
        school_zone: SchoolZone | None,
    ) -> SchoolPeriodType:
        if self._school_vacation_period_repo is None:
            return SchoolPeriodType.REGULAR
        periods = await self._school_vacation_period_repo.find_for_date(target_date, school_zone)
        if periods:
            return SchoolPeriodType.VACATION
        return SchoolPeriodType.REGULAR

    @staticmethod
    def _week_parity(target_date: date) -> WeekParity:
        week_number = target_date.isocalendar().week
        if week_number % 2 == 0:
            return WeekParity.EVEN
        return WeekParity.ODD

    async def _with_legacy_entries(
        self,
        plan: MealPlan,
        *,
        hydrate_recipe_snapshots: bool = False,
    ) -> MealPlan:
        entries = [
            entry
            for entry in await self._meal_plan_repo.find_legacy_entries(plan.date_start, plan.date_end)
            if entry.status == "active"
        ]
        if not entries:
            return plan

        slots = [slot.model_copy(deep=True) for slot in plan.slots]
        slot_indexes = {(slot.date, slot.slot_code): index for index, slot in enumerate(slots)}
        existing_legacy_ids = {
            (slot.date, slot.slot_code, item.legacy_id)
            for slot in slots
            for item in slot.items
            if item.legacy_id is not None
        }
        pending_counts_by_slot: dict[int, int] = {}
        pending_items: list[tuple[LegacyMealPlanEntry, int, int]] = []

        for entry in entries:
            slot_code = self._legacy_slot_code(entry.meal_slot_code_legacy)
            key = (entry.date, slot_code)
            slot_index = slot_indexes.get(key)
            if slot_index is None:
                slot_index = self._append_slot(slots, entry.date, slot_code)
                slot_indexes[key] = slot_index

            if (entry.date, slot_code, entry.legacy_id) in existing_legacy_ids:
                continue

            pending_offset = pending_counts_by_slot.get(slot_index, 0)
            pending_counts_by_slot[slot_index] = pending_offset + 1
            pending_items.append((entry, slot_index, len(slots[slot_index].items) + pending_offset))
            existing_legacy_ids.add((entry.date, slot_code, entry.legacy_id))

        hydrated_items = await asyncio.gather(*(
            self._legacy_entry_to_item(entry, position, hydrate_recipe_snapshot=hydrate_recipe_snapshots)
            for entry, _, position in pending_items
        ))
        for (_, slot_index, _), item in zip(pending_items, hydrated_items, strict=True):
            slot = slots[slot_index]
            slots[slot_index] = slot.model_copy(update={"items": [*slot.items, item]})

        return plan.model_copy(update={"slots": slots})

    async def _legacy_entry_to_item(
        self,
        entry: LegacyMealPlanEntry,
        position: int,
        *,
        hydrate_recipe_snapshot: bool = False,
    ) -> MealItem:
        if entry.entry_type == MealItemType.RECIPE and entry.recipe_uuid is not None:
            if not hydrate_recipe_snapshot:
                return MealItem(
                    position=position,
                    item_type=MealItemType.RECIPE,
                    headcount=entry.headcount,
                    recipe_uuid=entry.recipe_uuid,
                    recipe_snapshot=self._legacy_recipe_snapshot(entry, entry.recipe_uuid),
                    legacy_id=entry.legacy_id,
                )
            try:
                return MealItem(
                    position=position,
                    item_type=MealItemType.RECIPE,
                    headcount=entry.headcount,
                    recipe_uuid=entry.recipe_uuid,
                    recipe_snapshot=await self._get_recipe_snapshot(entry.recipe_uuid),
                    legacy_id=entry.legacy_id,
                )
            except Exception:
                return self._legacy_mixed_item(entry, position)

        if entry.entry_type == MealItemType.PREP_TASK and entry.note:
            return MealItem(
                position=position,
                item_type=MealItemType.PREP_TASK,
                note=entry.note,
                legacy_id=entry.legacy_id,
            )

        if entry.entry_type == MealItemType.NOTE and entry.note:
            return MealItem(
                position=position,
                item_type=MealItemType.NOTE,
                note=entry.note,
                legacy_id=entry.legacy_id,
            )

        return self._legacy_mixed_item(entry, position)

    @staticmethod
    def _legacy_recipe_snapshot(entry: LegacyMealPlanEntry, recipe_uuid: UUID) -> RecipeSnapshot:
        return RecipeSnapshot(
            recipe_uuid=recipe_uuid,
            title=entry.recipe_title or MealPlanService._legacy_item_label(entry),
            short_description=None,
            servings_default=entry.headcount or 1,
            total_duration_min=None,
            ingredients=[],
            snapshot_taken_at=datetime.now(timezone.utc),
            recipe_version=None,
        )

    @staticmethod
    def _legacy_mixed_item(entry: LegacyMealPlanEntry, position: int) -> MealItem:
        return MealItem(
            position=position,
            item_type=MealItemType.MIXED,
            note=MealPlanService._legacy_item_label(entry),
            legacy_id=entry.legacy_id,
        )

    @staticmethod
    def _legacy_item_label(entry: LegacyMealPlanEntry) -> str:
        if entry.note:
            return entry.note
        if entry.recipe_title:
            return entry.recipe_title
        if entry.ingredient_name:
            return entry.ingredient_name
        if entry.recipe_uuid is not None:
            return f"Recette legacy {entry.recipe_uuid}"
        if entry.ingredient_uuid is not None:
            return f"Ingrédient legacy {entry.ingredient_uuid}"
        return f"Entrée legacy #{entry.legacy_id}"

    @staticmethod
    def _legacy_slot_code(value: str | None) -> SlotCode:
        normalized = (value or "").strip().casefold()
        if normalized in LEGACY_LUNCH_SLOT_CODES:
            return "lunch"
        if normalized in LEGACY_DINNER_SLOT_CODES:
            return "dinner"
        return "dinner"

    async def _prepare_for_save(self, plan: MealPlan) -> MealPlan:
        slots = []
        for slot in plan.slots:
            items = [await self._hydrate_item_if_needed(item) for item in slot.items]
            slots.append(slot.model_copy(update={"items": self._renumber(items)}))
        return plan.model_copy(update={"slots": slots})

    async def _hydrate_item_if_needed(self, item: MealItem) -> MealItem:
        if item.item_type == MealItemType.RECIPE and item.recipe_uuid is not None and item.recipe_snapshot is None:
            return item.model_copy(update={"recipe_snapshot": await self._get_recipe_snapshot(item.recipe_uuid)})
        if item.item_type == MealItemType.INGREDIENT and item.ingredient_uuid is not None:
            return await self._hydrate_ingredient_item(item)
        return item

    async def _input_to_item(self, item: MealItemInput, position: int) -> MealItem:
        target_position = item.position if item.position is not None else position
        snapshot = item.recipe_snapshot
        if item.item_type == MealItemType.RECIPE and snapshot is None and item.recipe_uuid is not None:
            snapshot = await self._get_recipe_snapshot(item.recipe_uuid)
        ingredient_name = item.ingredient_name
        ingredient_unit = item.ingredient_unit
        if item.item_type == MealItemType.INGREDIENT:
            if item.ingredient_uuid is None:
                raise InvalidMealPlanOperation("ingredient item requires ingredient_uuid")
            ingredient = await self._get_ingredient_snapshot(item.ingredient_uuid)
            ingredient_name = ingredient.name
            ingredient_unit = ingredient.unit or ingredient_unit
        payload = {
            "position": target_position,
            "item_type": item.item_type,
            "headcount": item.headcount,
            "member_ids": item.member_ids,
            "recipe_uuid": item.recipe_uuid,
            "recipe_snapshot": snapshot,
            "ingredient_uuid": item.ingredient_uuid,
            "ingredient_name": ingredient_name,
            "ingredient_quantity": item.ingredient_quantity,
            "ingredient_unit": ingredient_unit,
            "note": item.note,
            "legacy_id": item.legacy_id,
        }
        if item.uuid is not None:
            payload["uuid"] = item.uuid
        return MealItem.model_validate(payload)

    @staticmethod
    def _item_headcount(item: MealItem, slot_headcount: int | None, fallback: int) -> int:
        if item.headcount is not None:
            return item.headcount
        if slot_headcount is not None and slot_headcount > 0:
            return slot_headcount
        return fallback

    @staticmethod
    def _slot_projection_headcount(slot: MealSlot) -> int:
        if slot.headcount is not None:
            return slot.headcount
        item_headcounts = [
            item.headcount
            for item in slot.items
            if item.item_type in (MealItemType.RECIPE, MealItemType.INGREDIENT) and item.headcount is not None
        ]
        if not item_headcounts:
            return 0
        return max(item_headcounts)

    async def _replace_item(
        self,
        items: list[MealItem],
        item_uuid: UUID,
        item_input: MealItemInput,
    ) -> list[MealItem]:
        result: list[MealItem] = []
        found = False
        for existing in items:
            if existing.uuid == item_uuid:
                found = True
                replacement = await self._input_to_item(
                    item_input.model_copy(update={"uuid": item_uuid, "position": existing.position}),
                    existing.position,
                )
                result.append(replacement)
            else:
                result.append(existing)
        if not found:
            raise InvalidMealPlanOperation(f"item {item_uuid} not found")
        return self._renumber(result)

    async def _apply_slot_operation(
        self,
        slots: list[MealSlot],
        slot_index: int,
        operation: SlotPatchOperation,
    ) -> list[MealSlot]:
        slot = slots[slot_index]
        if operation.op == "set_headcount":
            slot = slot.model_copy(
                update={
                    "headcount": operation.headcount,
                    "headcount_source": HeadcountSource.MANUAL,
                },
            )
        elif operation.op == "set_members":
            member_ids = await self._validated_slot_member_ids(operation.member_ids)
            slot = slot.model_copy(
                update={
                    "headcount": len(member_ids),
                    "headcount_source": HeadcountSource.MANUAL,
                    "member_ids": member_ids,
                },
            )
        elif operation.op == "add_item":
            if operation.item is None:
                raise InvalidMealPlanOperation("add_item requires item")
            self._assert_item_headcount(operation.item, slot)
            item = await self._input_to_item(operation.item, len(slot.items))
            slot = slot.model_copy(update={"items": [*slot.items, item]})
        elif operation.op == "update_item":
            if operation.item_uuid is None or operation.item is None:
                raise InvalidMealPlanOperation("update_item requires item_uuid and item")
            self._assert_item_headcount(operation.item, slot)
            slot = slot.model_copy(update={"items": await self._replace_item(slot.items, operation.item_uuid, operation.item)})
        elif operation.op == "remove_item":
            if operation.item_uuid is None:
                raise InvalidMealPlanOperation("remove_item requires item_uuid")
            slot = slot.model_copy(update={"items": self._renumber([item for item in slot.items if item.uuid != operation.item_uuid])})
        elif operation.op == "reorder_items":
            if operation.new_positions is None:
                raise InvalidMealPlanOperation("reorder_items requires new_positions")
            slot = slot.model_copy(update={"items": self._reorder(slot.items, operation.new_positions)})
        slots[slot_index] = slot
        return slots

    async def _get_recipe_snapshot(self, recipe_uuid: UUID) -> RecipeSnapshot:
        if self._recipe_client is None:
            raise InvalidMealPlanOperation("Recipe client is not configured")
        return await self._recipe_client.get_recipe_snapshot(recipe_uuid)

    async def _get_ingredient_snapshot(self, ingredient_uuid: UUID) -> IngredientSnapshot:
        if self._recipe_client is None:
            raise InvalidMealPlanOperation("Recipe client is not configured")
        return await self._recipe_client.get_ingredient_snapshot(ingredient_uuid)

    async def _hydrate_ingredient_item(self, item: MealItem) -> MealItem:
        if item.ingredient_uuid is None:
            raise InvalidMealPlanOperation("ingredient item requires ingredient_uuid")
        try:
            ingredient = await self._get_ingredient_snapshot(item.ingredient_uuid)
        except IngredientNotFound:
            raise
        unit = ingredient.unit or item.ingredient_unit
        return item.model_copy(
            update={
                "ingredient_name": ingredient.name,
                "ingredient_unit": unit,
            },
        )

    async def _enrich_recipe_status(self, plan: MealPlan) -> MealPlan:
        recipe_client = self._recipe_client
        if recipe_client is None:
            return plan
        status_tasks: dict[UUID, asyncio.Task[dict[str, str | int | None]]] = {}

        async def status_for(recipe_uuid: UUID) -> dict[str, str | int | None]:
            task = status_tasks.get(recipe_uuid)
            if task is None:
                task = asyncio.create_task(recipe_client.get_recipe_status(recipe_uuid))
                status_tasks[recipe_uuid] = task
            return await task

        async def enrich_item(item: MealItem) -> MealItem:
            if item.item_type != MealItemType.RECIPE or item.recipe_uuid is None:
                return item
            if item.legacy_id is not None:
                return item
            try:
                status = await status_for(item.recipe_uuid)
                current_version = status.get("version")
                snapshot_version = item.recipe_snapshot.recipe_version if item.recipe_snapshot else None
                return item.model_copy(
                    update={
                        "recipe_status": status.get("status"),
                        "recipe_modified": (
                            current_version is not None
                            and snapshot_version is not None
                            and current_version != snapshot_version
                        ),
                    },
                )
            except Exception:
                return item.model_copy(update={"recipe_status": "unknown", "recipe_modified": False})

        async def enrich_slot(slot: MealSlot) -> MealSlot:
            items = await asyncio.gather(*(enrich_item(item) for item in slot.items))
            return slot.model_copy(update={"items": items})

        slots = await asyncio.gather(*(enrich_slot(slot) for slot in plan.slots))
        return plan.model_copy(update={"slots": slots})

    async def _get_existing(self, uuid: UUID) -> MealPlan:
        existing = await super().read(_repository_uuid(uuid))
        if existing is None:
            raise MealPlanNotFound(f"MealPlan {uuid} not found")
        return existing

    async def _get_existing_school_vacation_period(self, uuid: UUID) -> SchoolVacationPeriod:
        if self._school_vacation_period_repo is None:
            raise SchoolVacationPeriodNotFound(f"SchoolVacationPeriod {uuid} not found")
        existing = await self._school_vacation_period_repo.read(_repository_uuid(uuid))
        if existing is None:
            raise SchoolVacationPeriodNotFound(f"SchoolVacationPeriod {uuid} not found")
        return existing

    async def _get_existing_household_member(self, uuid: UUID) -> HouseholdMember:
        if self._household_member_repo is None:
            raise HouseholdMemberNotFound(f"HouseholdMember {uuid} not found")
        existing = await self._household_member_repo.find(uuid)
        if existing is None:
            raise HouseholdMemberNotFound(f"HouseholdMember {uuid} not found")
        return existing

    async def _active_household_member_ids(self) -> set[UUID] | None:
        if self._household_member_repo is None:
            return None
        return {member.uuid for member in await self._household_member_repo.list_all()}

    async def _validated_slot_member_ids(self, member_ids: list[UUID]) -> list[UUID]:
        deduped_member_ids = list(dict.fromkeys(member_ids))
        active_member_ids = await self._active_household_member_ids()
        if active_member_ids is None:
            return deduped_member_ids

        unknown_member_ids = [member_id for member_id in deduped_member_ids if member_id not in active_member_ids]
        if unknown_member_ids:
            raise InvalidMealPlanOperation("slot member_ids contain unknown household members")
        return deduped_member_ids

    async def _normalize_household_schedule_rules(
        self,
        household_schedule_id: UUID,
        rules: list[HouseholdScheduleRule],
    ) -> list[HouseholdScheduleRule]:
        active_member_ids = await self._active_household_member_ids()
        normalized_rules: list[HouseholdScheduleRule] = []
        for rule in rules:
            updates: dict[str, object] = {"household_schedule_id": household_schedule_id}
            member_ids = list(dict.fromkeys(rule.member_ids))
            unknown_member_ids = [
                member_id
                for member_id in member_ids
                if active_member_ids is not None and member_id not in active_member_ids
            ]
            if unknown_member_ids:
                raise InvalidMealPlanOperation("household schedule rule references unknown household members")
            updates["member_ids"] = member_ids
            updates["headcount"] = len(member_ids)
            normalized_rules.append(rule.model_copy(update=updates))
        return normalized_rules

    async def _assert_household_schedule_rules_are_valid(self, rules: list[HouseholdScheduleRule]) -> None:
        slot_codes = set(await self._meal_slot_codes())
        seen: set[tuple[WeekParity, SchoolPeriodType, DayOfWeek, SlotCode]] = set()
        for rule in rules:
            if rule.meal_slot_code not in slot_codes:
                raise InvalidMealPlanOperation("household schedule rule references an undeclared meal slot")
            key = (rule.week_parity, rule.school_period_type, rule.day_of_week, rule.meal_slot_code)
            if key in seen:
                raise InvalidMealPlanOperation("duplicate household schedule rule")
            seen.add(key)

    async def _assert_no_confirmed_overlap(
        self,
        date_start: date,
        date_end: date,
        exclude_uuid: UUID | None = None,
    ) -> None:
        conflicts = await self._meal_plan_repo.find_overlapping_confirmed(date_start, date_end, exclude_uuid)
        if conflicts:
            raise OverlapWithConfirmedPlan([conflict.uuid for conflict in conflicts])

    @staticmethod
    def _assert_version(
        entity: MealPlan | TenantPreferences | HouseholdSchedule | SchoolVacationPeriod | HouseholdMember,
        expected_version: int,
    ) -> None:
        if entity.version != expected_version:
            raise VersionConflict(f"expected version {expected_version}, current version {entity.version}")

    @staticmethod
    def _assert_mutable(plan: MealPlan) -> None:
        if plan.status in (MealPlanStatus.DONE, MealPlanStatus.ABANDONED):
            raise InvalidMealPlanOperation(f"{plan.status.value} plans are read-only")

    @staticmethod
    def _assert_slot_date_inside_plan(plan: MealPlan, slot_date: date) -> None:
        if not plan.date_start <= slot_date <= plan.date_end:
            raise InvalidMealPlanOperation(f"slot {slot_date} outside plan period")

    @staticmethod
    def _find_slot_index(slots: list[MealSlot], slot_date: date, slot_code: SlotCode) -> int:
        for index, slot in enumerate(slots):
            if slot.date == slot_date and slot.slot_code == slot_code:
                return index
        raise InvalidMealPlanOperation(f"slot {slot_date} {slot_code} not found")

    @staticmethod
    def _find_slot_index_or_none(slots: list[MealSlot], slot_date: date, slot_code: SlotCode) -> int | None:
        for index, slot in enumerate(slots):
            if slot.date == slot_date and slot.slot_code == slot_code:
                return index
        return None

    @staticmethod
    def _append_slot(slots: list[MealSlot], slot_date: date, slot_code: SlotCode) -> int:
        slots.append(MealSlot(date=slot_date, slot_code=slot_code, headcount=None))
        return len(slots) - 1

    @staticmethod
    def _assert_global_slot_code(slot_code: SlotCode, slot_codes: tuple[SlotCode, ...]) -> None:
        if slot_code not in slot_codes:
            raise InvalidMealPlanOperation("slot_code must be declared globally before use")

    @staticmethod
    def _assert_item_headcount(item: MealItemInput, slot: MealSlot) -> None:
        if item.item_type not in (MealItemType.RECIPE, MealItemType.INGREDIENT):
            return
        if item.headcount is not None:
            return
        if slot.headcount is not None and slot.headcount > 0:
            return
        raise InvalidMealPlanOperation("headcount is required when adding a recipe or ingredient")

    @staticmethod
    def _renumber(items: list[MealItem]) -> list[MealItem]:
        return [item.model_copy(update={"position": index}) for index, item in enumerate(items)]

    @staticmethod
    def _reorder(items: list[MealItem], new_positions: dict[UUID, int]) -> list[MealItem]:
        if {item.uuid for item in items} != set(new_positions):
            raise InvalidMealPlanOperation("new_positions must reference all current items")
        reordered = [item.model_copy(update={"position": new_positions[item.uuid]}) for item in items]
        reordered.sort(key=lambda item: item.position)
        return MealPlanService._renumber(reordered)
