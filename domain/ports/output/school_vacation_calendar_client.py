from abc import ABC, abstractmethod
from datetime import date

from domain.models.enums import SchoolZone
from domain.models.school_vacation_period import SchoolVacationPeriod


class SchoolVacationCalendarClient(ABC):
    @abstractmethod
    async def fetch_periods(
        self,
        school_zone: SchoolZone,
        date_start: date,
        date_end: date,
    ) -> list[SchoolVacationPeriod]:
        """Fetch official school vacation periods overlapping the requested range."""
        pass
