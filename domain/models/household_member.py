from pydantic import Field, field_validator

from arclith.domain.models.entity import Entity
from domain.models.enums import Gender, MemberType


class HouseholdMember(Entity):
    name: str = Field(..., min_length=1, max_length=120)
    member_type: MemberType
    gender: Gender | None = None
    birth_year: int | None = Field(None, ge=1900, le=2100)
    avatar_data: str | None = None
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
