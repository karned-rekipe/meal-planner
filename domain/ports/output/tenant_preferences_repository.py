from abc import abstractmethod

from arclith.domain.ports.repository import Repository
from domain.models.tenant_preferences import TenantPreferences


class TenantPreferencesRepository(Repository[TenantPreferences]):
    @abstractmethod
    async def get_singleton(self) -> TenantPreferences | None:
        pass

    @abstractmethod
    async def save_singleton(self, preferences: TenantPreferences) -> TenantPreferences:
        pass
