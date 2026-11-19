from datetime import date

from arclith.adapters.output.memory.repository import InMemoryRepository
from domain.models.enums import SchoolZone, VacationPeriodSource
from domain.models.school_vacation_period import SchoolVacationPeriod
from domain.ports.output.school_vacation_period_repository import SchoolVacationPeriodRepository


class InMemorySchoolVacationPeriodRepository(
    InMemoryRepository[SchoolVacationPeriod],
    SchoolVacationPeriodRepository,
):
    async def find_for_date(
        self,
        target_date: date,
        school_zone: SchoolZone | None,
    ) -> list[SchoolVacationPeriod]:
        return [
            period
            for period in self._store.values()
            if not period.is_deleted
            and period.start_date <= target_date <= period.end_date
            and self._matches_zone(period, school_zone)
        ]

    @staticmethod
    def _matches_zone(period: SchoolVacationPeriod, school_zone: SchoolZone | None) -> bool:
        if period.source == VacationPeriodSource.MANUAL:
            return True
        if period.school_zone is None:
            return True
        return school_zone is not None and period.school_zone == school_zone
