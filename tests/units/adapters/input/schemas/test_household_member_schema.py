import pytest

from adapters.input.schemas.household_member_schema import (
    MAX_AVATAR_DATA_URI_LENGTH,
    HouseholdMemberAvatarPayload,
    HouseholdMemberPayload,
)


def test_household_member_payload_strips_name():
    payload = HouseholdMemberPayload(
        name="  Alice  ",
        member_type="resident",
        gender="female",
        birth_year=2018,
        color="#4a90d9",
    )

    member = payload.to_domain()

    assert payload.name == "Alice"
    assert member.name == "Alice"


def test_household_member_payload_rejects_empty_name():
    with pytest.raises(Exception):
        HouseholdMemberPayload(name=" ", member_type="resident", color="#4a90d9")


def test_household_member_payload_rejects_invalid_color():
    with pytest.raises(Exception):
        HouseholdMemberPayload(name="Alice", member_type="resident", color="blue")


def test_household_member_payload_rejects_birth_year_out_of_range():
    with pytest.raises(Exception):
        HouseholdMemberPayload(name="Alice", member_type="resident", birth_year=1899, color="#4a90d9")


def test_household_member_avatar_rejects_oversized_payload():
    with pytest.raises(Exception):
        HouseholdMemberAvatarPayload(avatar_data="x" * (MAX_AVATAR_DATA_URI_LENGTH + 1))
