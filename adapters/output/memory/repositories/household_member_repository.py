from datetime import datetime, timezone
from uuid import UUID as StdUUID

from arclith.adapters.output.memory.repository import InMemoryRepository
from domain.models.enums import MemberType
from domain.models.household_member import HouseholdMember
from domain.ports.output.household_member_repository import HouseholdMemberRepository
from uuid6 import UUID


class InMemoryHouseholdMemberRepository(
    InMemoryRepository[HouseholdMember],
    HouseholdMemberRepository,
):
    async def list_all(self) -> list[HouseholdMember]:
        members = [member for member in self._store.values() if not member.is_deleted]
        members.sort(key=lambda member: (member.member_type != MemberType.RESIDENT, member.name.casefold()))
        return members

    async def find(self, uuid: StdUUID) -> HouseholdMember | None:
        key = UUID(str(uuid))
        member = self._store.get(key)
        if member is None or member.is_deleted:
            return None
        return member

    async def save(self, member: HouseholdMember) -> HouseholdMember:
        self._store[member.uuid] = member
        return member

    async def delete(self, uuid: StdUUID) -> None:
        key = UUID(str(uuid))
        member = self._store.get(key)
        if member is None or member.is_deleted:
            return
        self._store[key] = member.model_copy(update={"deleted_at": datetime.now(timezone.utc)})
