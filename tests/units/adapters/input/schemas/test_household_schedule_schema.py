from datetime import date

import pytest
from uuid6 import uuid7

from adapters.input.schemas.household_schedule_schema import (
    HouseholdScheduleRulePayload,
    SchoolVacationPeriodPayload,
)
def test_household_schedule_rule_payload_strips_slot_code():
    member_ids = [uuid7()]
    payload = HouseholdScheduleRulePayload(
        week_parity="even",
        school_period_type="regular",
        day_of_week="monday",
        meal_slot_code="  lunch  ",
        member_ids=member_ids,
    )

    assert payload.meal_slot_code == "lunch"
    assert payload.to_domain(uuid7()).headcount == 1


def test_household_schedule_rule_requires_at_least_one_named_member():
    with pytest.raises(Exception):
        HouseholdScheduleRulePayload(
            week_parity="even",
            school_period_type="regular",
            day_of_week="monday",
            meal_slot_code="lunch",
            member_ids=[],
        )


def test_household_schedule_rule_members_mode_computes_headcount_and_keeps_members():
    member_ids = [uuid7(), uuid7()]
    payload = HouseholdScheduleRulePayload(
        week_parity="even",
        school_period_type="regular",
        day_of_week="monday",
        meal_slot_code="lunch",
        member_ids=member_ids,
    )

    rule = payload.to_domain(uuid7())

    assert rule.headcount == 2
    assert rule.member_ids == member_ids


def test_household_schedule_rule_deduplicates_named_members():
    member_id = uuid7()
    payload = HouseholdScheduleRulePayload(
        week_parity="even",
        school_period_type="regular",
        day_of_week="monday",
        meal_slot_code="lunch",
        member_ids=[member_id, member_id],
    )

    rule = payload.to_domain(uuid7())

    assert rule.headcount == 1
    assert rule.member_ids == [member_id]


def test_school_vacation_payload_validates_period():
    with pytest.raises(Exception):
        SchoolVacationPeriodPayload(
            source="manual",
            school_zone=None,
            name="Invalide",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 5),
        ).to_domain()
