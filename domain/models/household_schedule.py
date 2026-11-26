from uuid import UUID

from pydantic import Field, field_validator

from arclith.domain.models.entity import Entity
from domain.models.enums import DayOfWeek, ScheduleMode, SchoolPeriodType, SchoolZone, SlotCode, WeekParity


class HouseholdSchedule(Entity):
    school_zone: SchoolZone | None = None
    schedule_mode: ScheduleMode = ScheduleMode.MEMBERS


class HouseholdScheduleRule(Entity):
    household_schedule_id: UUID
    week_parity: WeekParity
    school_period_type: SchoolPeriodType
    day_of_week: DayOfWeek
    meal_slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    headcount: int = Field(..., ge=0, le=20)
    member_ids: list[UUID] = Field(default_factory=list)

    @field_validator("meal_slot_code", mode="before")
    @classmethod
    def strip_meal_slot_code(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("meal_slot_code cannot be empty")
        return stripped
