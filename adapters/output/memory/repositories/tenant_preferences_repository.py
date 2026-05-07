from uuid6 import uuid7

from arclith.adapters.output.memory.repository import InMemoryRepository
from domain.models.tenant_preferences import TenantPreferences
from domain.ports.output.tenant_preferences_repository import TenantPreferencesRepository


class InMemoryTenantPreferencesRepository(
    InMemoryRepository[TenantPreferences],
    TenantPreferencesRepository,
):
    async def get_singleton(self) -> TenantPreferences | None:
        active = [item for item in self._store.values() if not item.is_deleted]
        if not active:
            return None
        return active[0]

    async def save_singleton(self, preferences: TenantPreferences) -> TenantPreferences:
        current = await self.get_singleton()
        if current is None:
            entity = preferences.model_copy(update={"uuid": preferences.uuid or uuid7()})
            self._store[entity.uuid] = entity
            return entity
        updated = preferences.model_copy(update={"uuid": current.uuid, "version": preferences.version})
        self._store[current.uuid] = updated
        return updated
