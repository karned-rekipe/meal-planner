import json
from typing import Any
from uuid import UUID

from arclith.adapters.output.duckdb.repository import DuckDBRepository
from domain.models.enums import DayOfWeek, SchoolPeriodType, SlotCode, WeekParity
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.ports.output.household_schedule_repository import HouseholdScheduleRepository


class _DuckDBHouseholdScheduleRuleRepository(DuckDBRepository[HouseholdScheduleRule]):
    def _row_to_entity(self, row: dict[str, Any]) -> HouseholdScheduleRule:
        payload = dict(row)
        member_ids = payload.get("member_ids")
        if isinstance(member_ids, str):
            payload["member_ids"] = json.loads(member_ids)
        return super()._row_to_entity(payload)

    def _entity_to_row(self, entity: HouseholdScheduleRule) -> dict[str, Any]:
        row = super()._entity_to_row(entity)
        row["member_ids"] = json.dumps([str(member_id) for member_id in entity.member_ids])
        return row


class DuckDBHouseholdScheduleRepository(
    DuckDBRepository[HouseholdSchedule],
    HouseholdScheduleRepository,
):
    def __init__(self, path: str) -> None:
        super().__init__(path, HouseholdSchedule)
        self._rules = _DuckDBHouseholdScheduleRuleRepository(path, HouseholdScheduleRule)

    async def get_singleton(self) -> HouseholdSchedule | None:
        active = [item for item in await self.find_all() if not item.is_deleted]
        if not active:
            return None
        return active[0]

    async def save_singleton(self, schedule: HouseholdSchedule) -> HouseholdSchedule:
        current = await self.get_singleton()
        if current is None:
            return await self.create(schedule)
        return await self.update(schedule.model_copy(update={"uuid": current.uuid}))

    async def list_rules(self, household_schedule_id: UUID) -> list[HouseholdScheduleRule]:
        rules = [
            rule
            for rule in await self._rules.find_all()
            if not rule.is_deleted and rule.household_schedule_id == household_schedule_id
        ]
        rules.sort(key=lambda rule: (rule.week_parity, rule.school_period_type, rule.day_of_week, rule.meal_slot_code))
        return rules

    async def replace_rules(
        self,
        household_schedule_id: UUID,
        rules: list[HouseholdScheduleRule],
    ) -> list[HouseholdScheduleRule]:
        for rule in await self.list_rules(household_schedule_id):
            await self._rules.delete(rule.uuid)
        for rule in rules:
            await self._rules.create(rule.model_copy(update={"household_schedule_id": household_schedule_id}))
        return await self.list_rules(household_schedule_id)

    async def find_rule(
        self,
        household_schedule_id: UUID,
        *,
        week_parity: WeekParity,
        school_period_type: SchoolPeriodType,
        day_of_week: DayOfWeek,
        meal_slot_code: SlotCode,
    ) -> HouseholdScheduleRule | None:
        for rule in await self.list_rules(household_schedule_id):
            if (
                rule.week_parity == week_parity
                and rule.school_period_type == school_period_type
                and rule.day_of_week == day_of_week
                and rule.meal_slot_code == meal_slot_code
            ):
                return rule
        return None
