from datetime import date

from adapters.output.memory.repository import (
    InMemoryHouseholdScheduleRepository,
    InMemorySchoolVacationPeriodRepository,
)
from domain.models.enums import (
    DayOfWeek,
    SchoolPeriodType,
    SchoolZone,
    VacationPeriodSource,
    WeekParity,
)
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.models.school_vacation_period import SchoolVacationPeriod


async def test_household_schedule_singleton_and_rules():
    repo = InMemoryHouseholdScheduleRepository()
    schedule = await repo.save_singleton(HouseholdSchedule(school_zone=SchoolZone.A))
    rule = HouseholdScheduleRule(
        household_schedule_id=schedule.uuid,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        day_of_week=DayOfWeek.MONDAY,
        meal_slot_code="lunch",
        headcount=4,
    )

    await repo.replace_rules(schedule.uuid, [rule])
    found = await repo.find_rule(
        schedule.uuid,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        day_of_week=DayOfWeek.MONDAY,
        meal_slot_code="lunch",
    )

    assert await repo.get_singleton() == schedule
    assert found is not None
    assert found.headcount == 4


async def test_manual_vacation_period_matches_any_zone():
    repo = InMemorySchoolVacationPeriodRepository()
    await repo.create(
        SchoolVacationPeriod(
            source=VacationPeriodSource.MANUAL,
            school_zone=SchoolZone.C,
            name="Vacances maison",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 11),
        ),
    )

    periods = await repo.find_for_date(date(2026, 1, 6), SchoolZone.A)

    assert len(periods) == 1


async def test_official_vacation_period_matches_selected_zone():
    repo = InMemorySchoolVacationPeriodRepository()
    await repo.create(
        SchoolVacationPeriod(
            source=VacationPeriodSource.OFFICIAL,
            school_zone=SchoolZone.B,
            name="Vacances zone B",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 8),
        ),
    )

    assert await repo.find_for_date(date(2026, 2, 2), SchoolZone.A) == []
    assert len(await repo.find_for_date(date(2026, 2, 2), SchoolZone.B)) == 1
