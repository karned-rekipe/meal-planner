from abc import abstractmethod
from uuid import UUID

from arclith.domain.ports.repository import Repository
from domain.models.enums import DayOfWeek, SchoolPeriodType, SlotCode, WeekParity
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule


class HouseholdScheduleRepository(Repository[HouseholdSchedule]):
    @abstractmethod
    async def get_singleton(self) -> HouseholdSchedule | None:
        pass

    @abstractmethod
    async def save_singleton(self, schedule: HouseholdSchedule) -> HouseholdSchedule:
        pass

    @abstractmethod
    async def list_rules(self, household_schedule_id: UUID) -> list[HouseholdScheduleRule]:
        pass

    @abstractmethod
    async def replace_rules(
        self,
        household_schedule_id: UUID,
        rules: list[HouseholdScheduleRule],
    ) -> list[HouseholdScheduleRule]:
        pass

    @abstractmethod
    async def find_rule(
        self,
        household_schedule_id: UUID,
        *,
        week_parity: WeekParity,
        school_period_type: SchoolPeriodType,
        day_of_week: DayOfWeek,
        meal_slot_code: SlotCode,
    ) -> HouseholdScheduleRule | None:
        pass
