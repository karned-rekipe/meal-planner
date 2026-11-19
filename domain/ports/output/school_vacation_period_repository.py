from abc import abstractmethod
from datetime import date

from arclith.domain.ports.repository import Repository
from domain.models.enums import SchoolZone
from domain.models.school_vacation_period import SchoolVacationPeriod


class SchoolVacationPeriodRepository(Repository[SchoolVacationPeriod]):
    @abstractmethod
    async def find_for_date(
        self,
        target_date: date,
        school_zone: SchoolZone | None,
    ) -> list[SchoolVacationPeriod]:
        pass
