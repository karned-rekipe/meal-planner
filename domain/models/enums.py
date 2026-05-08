from enum import StrEnum

SlotCode = str
DEFAULT_SLOT_CODES: tuple[SlotCode, SlotCode] = ("lunch", "dinner")


class MealPlanStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    DONE = "done"
    ABANDONED = "abandoned"


class MealItemType(StrEnum):
    RECIPE = "recipe"
    INGREDIENT = "ingredient"
    NOTE = "note"
    PREP_TASK = "prep_task"
    MIXED = "mixed"


class HeadcountSource(StrEnum):
    HOUSEHOLD_SCHEDULE = "household_schedule"
    MANUAL = "manual"


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class MemberType(StrEnum):
    RESIDENT = "resident"
    RECURRING_GUEST = "recurring_guest"


class ScheduleMode(StrEnum):
    HEADCOUNT = "headcount"
    MEMBERS = "members"


class WeekParity(StrEnum):
    EVEN = "even"
    ODD = "odd"


class SchoolPeriodType(StrEnum):
    REGULAR = "regular"
    VACATION = "vacation"


class DayOfWeek(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class SchoolZone(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class VacationPeriodSource(StrEnum):
    OFFICIAL = "official"
    MANUAL = "manual"
