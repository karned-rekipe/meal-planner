from pydantic import BaseModel, Field, field_validator

from arclith.adapters.input.schemas.base_schema import BaseSchema
from domain.models.enums import Gender, MemberType
from domain.models.household_member import HouseholdMember

MAX_AVATAR_DATA_URI_LENGTH = 2_800_000


class HouseholdMemberPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    member_type: MemberType
    gender: Gender | None = None
    birth_year: int | None = Field(None, ge=1900, le=2100)
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    def to_domain(self) -> HouseholdMember:
        return HouseholdMember(
            name=self.name,
            member_type=self.member_type,
            gender=self.gender,
            birth_year=self.birth_year,
            color=self.color,
        )


class HouseholdMemberAvatarPayload(BaseModel):
    avatar_data: str = Field(..., min_length=1, max_length=MAX_AVATAR_DATA_URI_LENGTH)


class HouseholdMemberSchema(BaseSchema):
    name: str
    member_type: MemberType
    gender: Gender | None
    birth_year: int | None
    avatar_data: str | None
    color: str
