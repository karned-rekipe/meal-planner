from datetime import date, datetime, timezone

import pytest
from uuid6 import uuid7

from adapters.output.memory.repository import (
    InMemoryHouseholdMemberRepository,
    InMemoryHouseholdScheduleRepository,
    InMemorySchoolVacationPeriodRepository,
)
from application.services.meal_plan_service import MealPlanService, SlotPatchOperation
from domain.models.enums import (
    DayOfWeek,
    HeadcountSource,
    MemberType,
    MealItemType,
    SchoolPeriodType,
    SchoolZone,
    VacationPeriodSource,
    WeekParity,
)
from domain.exceptions import InvalidMealPlanOperation, SchoolVacationCalendarUnavailable
from domain.models.household_member import HouseholdMember
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.models.recipe_snapshot import RecipeSnapshot
from domain.models.school_vacation_period import SchoolVacationPeriod
from tests.units.factories import meal_plan as build_meal_plan


class FakeSchoolVacationCalendarClient:
    async def fetch_periods(self, school_zone, date_start, date_end):
        return [
            SchoolVacationPeriod(
                source=VacationPeriodSource.OFFICIAL,
                school_zone=school_zone,
                name="Vacances d'hiver",
                start_date=date(2027, 2, 13),
                end_date=date(2027, 2, 28),
            ),
            SchoolVacationPeriod(
                source=VacationPeriodSource.OFFICIAL,
                school_zone=school_zone,
                name="Vacances de printemps",
                start_date=date(2027, 4, 10),
                end_date=date(2027, 4, 25),
            ),
        ]


class EmptySchoolVacationCalendarClient:
    async def fetch_periods(self, school_zone, date_start, date_end):
        return []


@pytest.fixture
def service(repo, logger):
    return MealPlanService(repo, logger)


async def test_create_and_read(service):
    meal_plan = await service.create(build_meal_plan(name="Farine"))
    found = await service.read(meal_plan.uuid)
    assert found is not None
    assert found.name == "Farine"


async def test_update(service):
    meal_plan = await service.create(build_meal_plan(name="Farine"))
    updated = await service.update(meal_plan.model_copy(update={"name": "Farine complète"}))
    assert updated.name == "Farine complète"
    assert updated.version == 2


async def test_delete_hides_from_read(service):
    meal_plan = await service.create(build_meal_plan(name="Sel"))
    await service.delete(meal_plan.uuid)
    assert await service.read(meal_plan.uuid) is None


async def test_find_all(service):
    await service.create(build_meal_plan(name="Farine"))
    await service.create(build_meal_plan(name="Sel"))
    result = await service.find_all()
    assert len(result) == 2


async def test_find_by_name(service):
    await service.create(build_meal_plan(name="Farine de blé"))
    await service.create(build_meal_plan(name="Sel fin"))
    result = await service.find_by_name("farine")
    assert len(result) == 1
    assert result[0].name == "Farine de blé"


async def test_duplicate(service):
    meal_plan = await service.create(build_meal_plan(name="Farine"))
    clone = await service.duplicate(meal_plan.uuid)
    assert clone.uuid != meal_plan.uuid
    assert clone.name == "Farine"


async def test_read_unknown_returns_none(service):
    assert await service.read(uuid7()) is None


async def test_find_by_name_no_results(service):
    await service.create(build_meal_plan(name="Sel"))
    result = await service.find_by_name("farine")
    assert result == []


@pytest.fixture
def scheduled_service(repo, logger):
    return MealPlanService(
        repo,
        logger,
        household_member_repository=InMemoryHouseholdMemberRepository(),
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=InMemorySchoolVacationPeriodRepository(),
    )


@pytest.fixture
def scheduled_members_service(repo, logger):
    return MealPlanService(
        repo,
        logger,
        household_member_repository=InMemoryHouseholdMemberRepository(),
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=InMemorySchoolVacationPeriodRepository(),
    )


async def _configure_rule(
    service: MealPlanService,
    *,
    week_parity: WeekParity,
    school_period_type: SchoolPeriodType,
    headcount: int,
) -> None:
    member_ids = []
    for index in range(headcount):
        member = await service.create_household_member(
            HouseholdMember(
                name=f"Personne {index + 1}",
                member_type=MemberType.RESIDENT,
                color="#2E8B57",
            ),
        )
        member_ids.append(member.uuid)
    schedule, _ = await service.get_household_schedule()
    await service.update_household_schedule(
        HouseholdSchedule(school_zone=SchoolZone.A),
        [
            HouseholdScheduleRule(
                household_schedule_id=schedule.uuid,
                week_parity=week_parity,
                school_period_type=school_period_type,
                day_of_week=DayOfWeek.MONDAY,
                meal_slot_code="lunch",
                headcount=0,
                member_ids=member_ids,
            )
        ],
        schedule.version,
    )


async def test_create_applies_even_regular_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=4,
    )

    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 5), date_end=date(2026, 1, 5)))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount == 4
    assert lunch.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE


async def test_create_applies_odd_regular_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.ODD,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=3,
    )

    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 12), date_end=date(2026, 1, 12)))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount == 3
    assert lunch.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE


async def test_create_applies_even_vacation_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.VACATION,
        headcount=6,
    )
    await scheduled_service.create_school_vacation_period(
        SchoolVacationPeriod(
            source=VacationPeriodSource.MANUAL,
            name="Vacances test",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 11),
        ),
    )

    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 5), date_end=date(2026, 1, 5)))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount == 6
    assert lunch.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE


async def test_create_applies_odd_vacation_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.ODD,
        school_period_type=SchoolPeriodType.VACATION,
        headcount=7,
    )
    await scheduled_service.create_school_vacation_period(
        SchoolVacationPeriod(
            source=VacationPeriodSource.MANUAL,
            name="Vacances test",
            start_date=date(2026, 1, 12),
            end_date=date(2026, 1, 18),
        ),
    )

    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 12), date_end=date(2026, 1, 12)))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount == 7
    assert lunch.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE


async def test_manual_headcount_change_does_not_update_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=4,
    )
    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 5), date_end=date(2026, 1, 5)))

    updated = await scheduled_service.patch_slots(
        plan.uuid,
        [
            SlotPatchOperation(
                op="set_headcount",
                slot_date=date(2026, 1, 5),
                slot_code="lunch",
                headcount=2,
            ),
        ],
        expected_version=plan.version,
    )

    lunch = next(slot for slot in updated.slots if slot.slot_code == "lunch")
    _, rules = await scheduled_service.get_household_schedule()

    assert lunch.headcount == 2
    assert lunch.headcount_source == HeadcountSource.MANUAL
    assert rules[0].headcount == 4


async def test_missing_household_schedule_rule_leaves_headcount_empty(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=4,
    )

    plan = await scheduled_service.create(build_meal_plan(date_start=date(2026, 1, 6), date_end=date(2026, 1, 6)))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount is None
    assert lunch.headcount_source is None


async def test_calendar_projection_applies_household_schedule(scheduled_service):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=4,
    )

    plan = await scheduled_service.get_calendar(date(2026, 1, 5), date(2026, 1, 5))
    lunch = next(slot for slot in plan.slots if slot.slot_code == "lunch")

    assert lunch.headcount == 4
    assert lunch.headcount_source == HeadcountSource.HOUSEHOLD_SCHEDULE


async def test_members_schedule_rejects_unknown_member_ids(scheduled_members_service):
    aubin = await scheduled_members_service.create_household_member(
        HouseholdMember(name="Aubin", member_type=MemberType.RESIDENT, color="#2E8B57"),
    )
    aurelie = await scheduled_members_service.create_household_member(
        HouseholdMember(name="Aurélie", member_type=MemberType.RESIDENT, color="#7C3AED"),
    )
    inactive = uuid7()
    schedule, _ = await scheduled_members_service.get_household_schedule()
    with pytest.raises(InvalidMealPlanOperation):
        await scheduled_members_service.update_household_schedule(
            HouseholdSchedule(school_zone=SchoolZone.A),
            [
                HouseholdScheduleRule(
                    household_schedule_id=schedule.uuid,
                    week_parity=WeekParity.EVEN,
                    school_period_type=SchoolPeriodType.REGULAR,
                    day_of_week=DayOfWeek.MONDAY,
                    meal_slot_code="lunch",
                    headcount=9,
                    member_ids=[aubin.uuid, inactive, aurelie.uuid],
                )
            ],
            schedule.version,
        )


async def test_calendar_patch_persists_only_user_calendar_overrides(scheduled_service, repo):
    await _configure_rule(
        scheduled_service,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        headcount=4,
    )

    projected = await scheduled_service.patch_calendar(
        [
            SlotPatchOperation(
                op="set_headcount",
                slot_date=date(2026, 1, 5),
                slot_code="lunch",
                headcount=2,
            ),
        ],
        date_start=date(2026, 1, 5),
        date_end=date(2026, 1, 11),
    )

    stored = (await repo.find_all())[0]
    stored_lunch = next(slot for slot in stored.slots if slot.slot_code == "lunch")
    projected_lunch = next(slot for slot in projected.slots if slot.date == date(2026, 1, 5) and slot.slot_code == "lunch")

    assert len(stored.slots) == 1
    assert stored_lunch.headcount == 2
    assert stored_lunch.headcount_source == HeadcountSource.MANUAL
    assert projected_lunch.headcount == 2
    assert projected_lunch.headcount_source == HeadcountSource.MANUAL


async def test_calendar_patch_persists_recipe_member_ids(scheduled_service, repo):
    recipe_uuid = uuid7()
    member_ids = [uuid7(), uuid7()]

    projected = await scheduled_service.patch_calendar(
        [
            SlotPatchOperation(
                op="add_item",
                slot_date=date(2026, 1, 5),
                slot_code="lunch",
                item={
                    "item_type": MealItemType.RECIPE,
                    "recipe_uuid": recipe_uuid,
                    "recipe_snapshot": RecipeSnapshot(
                        recipe_uuid=recipe_uuid,
                        title="Soupe",
                        servings_default=2,
                        ingredients=[],
                        snapshot_taken_at=datetime.now(timezone.utc),
                    ),
                    "headcount": 2,
                    "member_ids": member_ids,
                },
            ),
        ],
        date_start=date(2026, 1, 5),
        date_end=date(2026, 1, 5),
    )

    stored = (await repo.find_all())[0]
    stored_item = stored.slots[0].items[0]
    projected_item = next(slot for slot in projected.slots if slot.slot_code == "lunch").items[0]

    assert stored_item.member_ids == member_ids
    assert projected_item.member_ids == member_ids


async def test_calendar_patch_sets_slot_member_ids(scheduled_members_service, repo):
    aubin = await scheduled_members_service.create_household_member(
        HouseholdMember(name="Aubin", member_type=MemberType.RESIDENT, color="#7C3AED"),
    )
    ethel = await scheduled_members_service.create_household_member(
        HouseholdMember(name="Ethel", member_type=MemberType.RESIDENT, color="#047857"),
    )

    projected = await scheduled_members_service.patch_calendar(
        [
            SlotPatchOperation(
                op="set_members",
                slot_date=date(2026, 1, 5),
                slot_code="lunch",
                member_ids=[aubin.uuid, ethel.uuid, aubin.uuid],
            ),
        ],
        date_start=date(2026, 1, 5),
        date_end=date(2026, 1, 5),
    )

    stored = (await repo.find_all())[0]
    stored_slot = stored.slots[0]
    projected_slot = next(slot for slot in projected.slots if slot.slot_code == "lunch")

    assert stored_slot.member_ids == [aubin.uuid, ethel.uuid]
    assert stored_slot.headcount == 2
    assert stored_slot.headcount_source == HeadcountSource.MANUAL
    assert projected_slot.member_ids == [aubin.uuid, ethel.uuid]
    assert projected_slot.headcount == 2


async def test_calendar_patch_rejects_unknown_slot_member_ids(scheduled_members_service):
    with pytest.raises(InvalidMealPlanOperation):
        await scheduled_members_service.patch_calendar(
            [
                SlotPatchOperation(
                    op="set_members",
                    slot_date=date(2026, 1, 5),
                    slot_code="lunch",
                    member_ids=[uuid7()],
                ),
            ],
            date_start=date(2026, 1, 5),
            date_end=date(2026, 1, 5),
        )


async def test_duplicate_household_schedule_rule_is_rejected(scheduled_service):
    schedule, _ = await scheduled_service.get_household_schedule()
    rule = HouseholdScheduleRule(
        household_schedule_id=schedule.uuid,
        week_parity=WeekParity.EVEN,
        school_period_type=SchoolPeriodType.REGULAR,
        day_of_week=DayOfWeek.MONDAY,
        meal_slot_code="lunch",
        headcount=4,
    )

    with pytest.raises(InvalidMealPlanOperation):
        await scheduled_service.update_household_schedule(
            HouseholdSchedule(school_zone=SchoolZone.A),
            [rule, rule.model_copy()],
            schedule.version,
        )


async def test_official_school_vacation_sync_is_idempotent_and_preserves_manual_periods(repo, logger):
    service = MealPlanService(
        repo,
        logger,
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=InMemorySchoolVacationPeriodRepository(),
        school_vacation_calendar_client=FakeSchoolVacationCalendarClient(),
    )
    schedule, _ = await service.get_household_schedule()
    await service.update_household_school_zone(SchoolZone.A, schedule.version)
    manual = await service.create_school_vacation_period(
        SchoolVacationPeriod(
            source=VacationPeriodSource.MANUAL,
            name="Congé familial",
            start_date=date(2027, 5, 1),
            end_date=date(2027, 5, 3),
        ),
    )

    first = await service.sync_official_school_vacation_periods(
        date_start=date(2027, 1, 1),
        date_end=date(2027, 12, 31),
    )
    second = await service.sync_official_school_vacation_periods(
        date_start=date(2027, 1, 1),
        date_end=date(2027, 12, 31),
    )

    assert first[0] == SchoolZone.A
    assert first[3:6] == (2, 0, 0)
    assert second[3:6] == (0, 0, 0)
    assert {period.name for period in await service.list_school_vacation_periods()} == {
        "Vacances d'hiver",
        "Vacances de printemps",
        manual.name,
    }


async def test_official_school_vacation_sync_preserves_existing_periods_when_source_is_empty(repo, logger):
    period_repo = InMemorySchoolVacationPeriodRepository()
    service = MealPlanService(
        repo,
        logger,
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=period_repo,
        school_vacation_calendar_client=EmptySchoolVacationCalendarClient(),
    )
    schedule, _ = await service.get_household_schedule()
    await service.update_household_school_zone(SchoolZone.A, schedule.version)
    existing = await period_repo.create(
        SchoolVacationPeriod(
            source=VacationPeriodSource.OFFICIAL,
            school_zone=SchoolZone.A,
            name="Vacances existantes",
            start_date=date(2027, 2, 1),
            end_date=date(2027, 2, 10),
        ),
    )

    with pytest.raises(SchoolVacationCalendarUnavailable):
        await service.sync_official_school_vacation_periods(
            date_start=date(2027, 1, 1),
            date_end=date(2027, 12, 31),
        )

    assert [period.uuid for period in await period_repo.find_all()] == [existing.uuid]
