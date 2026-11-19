from adapters.output.memory.repository import InMemoryHouseholdMemberRepository
from domain.models.enums import Gender, MemberType
from domain.models.household_member import HouseholdMember


async def test_household_member_repository_crud():
    repo = InMemoryHouseholdMemberRepository()
    member = HouseholdMember(
        name=" Alice ",
        member_type=MemberType.RESIDENT,
        gender=Gender.FEMALE,
        birth_year=2018,
        color="#4a90d9",
    )

    saved = await repo.save(member)
    found = await repo.find(saved.uuid)

    assert found == saved
    assert found is not None
    assert found.name == "Alice"

    updated = saved.model_copy(update={"name": "Alice B.", "version": saved.version + 1})
    await repo.save(updated)

    listed = await repo.list_all()
    assert listed == [updated]

    await repo.delete(saved.uuid)

    assert await repo.find(saved.uuid) is None
    assert await repo.list_all() == []


async def test_household_member_repository_sorts_residents_before_guests():
    repo = InMemoryHouseholdMemberRepository()
    guest = HouseholdMember(name="Zoé", member_type=MemberType.RECURRING_GUEST, color="#d94a4a")
    resident = HouseholdMember(name="Anna", member_type=MemberType.RESIDENT, color="#4a90d9")

    await repo.save(guest)
    await repo.save(resident)

    assert [member.name for member in await repo.list_all()] == ["Anna", "Zoé"]
