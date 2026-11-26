from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from domain.exceptions import SchoolVacationCalendarUnavailable
from domain.models.enums import SchoolZone, VacationPeriodSource
from domain.models.school_vacation_period import SchoolVacationPeriod
from domain.ports.output.school_vacation_calendar_client import SchoolVacationCalendarClient

DEFAULT_CALENDAR_API_URL = (
    "https://data.education.gouv.fr/api/records/1.0/search/"
)
DEFAULT_CALENDAR_DATASET = "fr-en-calendrier-scolaire"
PARIS_TIMEZONE = ZoneInfo("Europe/Paris")


class OfficialSchoolVacationCalendarClient(SchoolVacationCalendarClient):
    def __init__(
        self,
        base_url: str = DEFAULT_CALENDAR_API_URL,
        dataset: str = DEFAULT_CALENDAR_DATASET,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._dataset = dataset
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def fetch_periods(
        self,
        school_zone: SchoolZone,
        date_start: date,
        date_end: date,
    ) -> list[SchoolVacationPeriod]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = await client.get(
                    self._base_url,
                    params={
                        "dataset": self._dataset,
                        "rows": 1000,
                        "sort": "start_date",
                        "refine.zones": f"Zone {school_zone.value}",
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SchoolVacationCalendarUnavailable(
                "Le calendrier officiel des vacances scolaires est temporairement indisponible."
            ) from exc

        records = payload.get("records")
        if not isinstance(records, list):
            raise SchoolVacationCalendarUnavailable(
                "La réponse du calendrier officiel des vacances scolaires est invalide."
            )

        periods: dict[tuple[str, date, date], SchoolVacationPeriod] = {}
        for record in records:
            fields = record.get("fields") if isinstance(record, dict) else None
            period = self._to_period(fields, school_zone)
            if period is None:
                continue
            if period.end_date < date_start or period.start_date > date_end:
                continue
            periods[(period.name, period.start_date, period.end_date)] = period

        return sorted(periods.values(), key=lambda period: (period.start_date, period.end_date, period.name))

    @staticmethod
    def _to_period(fields: Any, school_zone: SchoolZone) -> SchoolVacationPeriod | None:
        if not isinstance(fields, dict):
            return None
        name = fields.get("description")
        population = fields.get("population")
        start_value = fields.get("start_date")
        end_value = fields.get("end_date")
        if not isinstance(name, str) or not name.startswith("Vacances"):
            return None
        if population not in (None, "-", "Élèves"):
            return None
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            return None

        try:
            start_date = datetime.fromisoformat(start_value).astimezone(PARIS_TIMEZONE).date()
            resumption_date = datetime.fromisoformat(end_value).astimezone(PARIS_TIMEZONE).date()
        except ValueError:
            return None

        end_date = resumption_date - timedelta(days=1)
        if end_date < start_date:
            return None
        return SchoolVacationPeriod(
            source=VacationPeriodSource.OFFICIAL,
            school_zone=school_zone,
            name=name,
            start_date=start_date,
            end_date=end_date,
        )
