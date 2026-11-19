from typing import Any

from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from domain.models.tenant_preferences import TenantPreferences
from domain.ports.output.tenant_preferences_repository import TenantPreferencesRepository


class MongoDBTenantPreferencesRepository(
    MongoDBRepository[TenantPreferences],
    TenantPreferencesRepository,
):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        collection_config = MongoDBConfig(
            uri=config.uri,
            db_name=config.db_name,
            collection_name="tenant_preferences",
        )
        super().__init__(collection_config, TenantPreferences, logger)

    def _to_doc(self, entity: TenantPreferences) -> dict[str, Any]:
        doc = entity.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        return doc

    async def get_singleton(self) -> TenantPreferences | None:
        async with self._collection() as col:
            doc = await col.find_one({"deleted_at": None})
        return self._from_doc(doc) if doc else None

    async def save_singleton(self, preferences: TenantPreferences) -> TenantPreferences:
        current = await self.get_singleton()
        async with self._collection() as col:
            if current is None:
                await col.insert_one(self._to_doc(preferences))
                return preferences
            updated = preferences.model_copy(update={"uuid": current.uuid})
            await col.replace_one({"_id": str(current.uuid)}, self._to_doc(updated))
            return updated
