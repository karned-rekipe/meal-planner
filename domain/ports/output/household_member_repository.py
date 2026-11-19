from abc import abstractmethod
from uuid import UUID

from arclith.domain.ports.repository import Repository
from domain.models.household_member import HouseholdMember


class HouseholdMemberRepository(Repository[HouseholdMember]):
    @abstractmethod
    async def list_all(self) -> list[HouseholdMember]:
        pass

    @abstractmethod
    async def find(self, uuid: UUID) -> HouseholdMember | None:
        pass

    @abstractmethod
    async def save(self, member: HouseholdMember) -> HouseholdMember:
        pass

    @abstractmethod
    async def delete(self, uuid: UUID) -> None:
        pass
