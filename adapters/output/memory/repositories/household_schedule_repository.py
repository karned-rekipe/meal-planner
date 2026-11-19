from uuid import UUID

from uuid6 import uuid7

from arclith.adapters.output.memory.repository import InMemoryRepository
from domain.models.enums import DayOfWeek, SchoolPeriodType, SlotCode, WeekParity
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.ports.output.household_schedule_repository import HouseholdScheduleRepository


class InMemoryHouseholdScheduleRepository(
    InMemoryRepository[HouseholdSchedule],
    HouseholdScheduleRepository,
):
    def __init__(self) -> None:
        super().__init__()
        self._rules: dict[UUID, HouseholdScheduleRule] = {}

    async def get_singleton(self) -> HouseholdSchedule | None:
        active = [item for item in self._store.values() if not item.is_deleted]
        if not active:
            return None
        return active[0]

    async def save_singleton(self, schedule: HouseholdSchedule) -> HouseholdSchedule:
        current = await self.get_singleton()
        if current is None:
            entity = schedule.model_copy(update={"uuid": schedule.uuid or uuid7()})
            self._store[entity.uuid] = entity
            return entity
        updated = schedule.model_copy(update={"uuid": current.uuid, "version": schedule.version})
        self._store[current.uuid] = updated
        return updated

    async def list_rules(self, household_schedule_id: UUID) -> list[HouseholdScheduleRule]:
        rules = [
            rule
            for rule in self._rules.values()
            if not rule.is_deleted and rule.household_schedule_id == household_schedule_id
        ]
        rules.sort(key=lambda rule: (rule.week_parity, rule.school_period_type, rule.day_of_week, rule.meal_slot_code))
        return rules

    async def replace_rules(
        self,
        household_schedule_id: UUID,
        rules: list[HouseholdScheduleRule],
    ) -> list[HouseholdScheduleRule]:
        self._rules = {
            uuid: rule
            for uuid, rule in self._rules.items()
            if rule.household_schedule_id != household_schedule_id
        }
        for rule in rules:
            stored = rule.model_copy(update={"household_schedule_id": household_schedule_id})
            self._rules[stored.uuid] = stored
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
