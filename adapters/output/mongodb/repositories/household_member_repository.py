from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from domain.models.enums import MemberType
from domain.models.household_member import HouseholdMember
from domain.ports.output.household_member_repository import HouseholdMemberRepository


class MongoDBHouseholdMemberRepository(
    MongoDBRepository[HouseholdMember],
    HouseholdMemberRepository,
):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        collection_config = MongoDBConfig(
            uri=config.uri,
            db_name=config.db_name,
            collection_name="household_members",
        )
        super().__init__(collection_config, HouseholdMember, logger)

    def _to_doc(self, entity: HouseholdMember) -> dict[str, Any]:
        doc = entity.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        return doc

    async def list_all(self) -> list[HouseholdMember]:
        async with self._collection() as col:
            docs = await col.find({"deleted_at": None}).to_list(length=None)
        members = [self._from_doc(doc) for doc in docs]
        members.sort(key=lambda member: (member.member_type != MemberType.RESIDENT, member.name.casefold()))
        return members

    async def find(self, uuid: UUID) -> HouseholdMember | None:
        async with self._collection() as col:
            doc = await col.find_one({"_id": str(uuid), "deleted_at": None})
        return self._from_doc(doc) if doc else None

    async def save(self, member: HouseholdMember) -> HouseholdMember:
        async with self._collection() as col:
            await col.replace_one({"_id": str(member.uuid)}, self._to_doc(member), upsert=True)
        return member

    async def delete(self, uuid: UUID) -> None:
        async with self._collection() as col:
            await col.update_one(
                {"_id": str(uuid), "deleted_at": None},
                {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
            )
