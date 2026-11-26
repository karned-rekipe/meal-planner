from datetime import date
from typing import Literal
from uuid import UUID as StdUUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arclith.adapters.input.schemas.base_schema import BaseSchema
from domain.models.enums import (
    DayOfWeek,
    ScheduleMode,
    SchoolPeriodType,
    SchoolZone,
    SlotCode,
    VacationPeriodSource,
    WeekParity,
)
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.models.school_vacation_period import SchoolVacationPeriod


def _strip_slot_code(value: object) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("meal_slot_code cannot be empty")
    return stripped


class HouseholdScheduleRulePayload(BaseModel):
    week_parity: WeekParity
    school_period_type: SchoolPeriodType
    day_of_week: DayOfWeek
    meal_slot_code: SlotCode = Field(..., min_length=1, max_length=80)
    member_ids: list[StdUUID] = Field(..., min_length=1, max_length=20)

    @field_validator("meal_slot_code", mode="before")
    @classmethod
    def strip_meal_slot_code(cls, value: object) -> object:
        return _strip_slot_code(value)

    def to_domain(
        self,
        household_schedule_id: StdUUID,
    ) -> HouseholdScheduleRule:
        member_ids = list(dict.fromkeys(self.member_ids))
        return HouseholdScheduleRule(
            household_schedule_id=household_schedule_id,
            week_parity=self.week_parity,
            school_period_type=self.school_period_type,
            day_of_week=self.day_of_week,
            meal_slot_code=self.meal_slot_code,
            headcount=len(member_ids),
            member_ids=member_ids,
        )


class HouseholdScheduleRuleSchema(BaseSchema):
    household_schedule_id: StdUUID
    week_parity: WeekParity
    school_period_type: SchoolPeriodType
    day_of_week: DayOfWeek
    meal_slot_code: SlotCode
    headcount: int
    member_ids: list[StdUUID] = Field(default_factory=list)


class HouseholdScheduleUpdateSchema(BaseModel):
    school_zone: SchoolZone | None = None
    schedule_mode: Literal["members"] = "members"
    rules: list[HouseholdScheduleRulePayload] = Field(default_factory=list)

    def to_domain(self) -> HouseholdSchedule:
        return HouseholdSchedule(school_zone=self.school_zone, schedule_mode=ScheduleMode.MEMBERS)


class HouseholdScheduleSchema(BaseSchema):
    school_zone: SchoolZone | None = None
    schedule_mode: Literal["members"] = "members"
    rules: list[HouseholdScheduleRuleSchema] = Field(default_factory=list)


class HouseholdSchoolZoneUpdateSchema(BaseModel):
    school_zone: SchoolZone | None = None


class SchoolVacationCalendarSyncSchema(BaseModel):
    school_zone: SchoolZone | None = None
    date_start: date | None = None
    date_end: date | None = None


class SchoolVacationPeriodPayload(BaseModel):
    source: VacationPeriodSource
    school_zone: SchoolZone | None = None
    name: str = Field(..., min_length=1, max_length=120)
    start_date: date
    end_date: date

    def to_domain(self) -> SchoolVacationPeriod:
        return SchoolVacationPeriod(
            source=self.source,
            school_zone=self.school_zone,
            name=self.name,
            start_date=self.start_date,
            end_date=self.end_date,
        )


class SchoolVacationPeriodSchema(BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    source: VacationPeriodSource
    school_zone: SchoolZone | None = None
    name: str
    start_date: date
    end_date: date


class SchoolVacationCalendarSyncResultSchema(BaseModel):
    school_zone: SchoolZone
    date_start: date
    date_end: date
    created: int
    updated: int
    deleted: int
    periods: list[SchoolVacationPeriodSchema]


def household_schedule_to_schema(
    schedule: HouseholdSchedule,
    rules: list[HouseholdScheduleRule],
) -> HouseholdScheduleSchema:
    payload = schedule.model_dump()
    payload["schedule_mode"] = "members"
    payload["rules"] = [HouseholdScheduleRuleSchema.model_validate(rule, from_attributes=True) for rule in rules]
    return HouseholdScheduleSchema.model_validate(payload)
