import json
from datetime import date

import httpx

from adapters.output.http.school_vacation_calendar_client import OfficialSchoolVacationCalendarClient
from domain.models.enums import SchoolZone


def _record(
    description: str,
    start_date: str,
    end_date: str,
    population: str = "-",
) -> dict:
    return {
        "fields": {
            "description": description,
            "start_date": start_date,
            "end_date": end_date,
            "population": population,
        },
    }


async def test_fetch_periods_filters_deduplicates_and_uses_french_dates():
    payload = {
        "records": [
            _record(
                "Vacances de la Toussaint",
                "2026-10-16T22:00:00+00:00",
                "2026-11-01T23:00:00+00:00",
            ),
            _record(
                "Vacances de la Toussaint",
                "2026-10-16T22:00:00+00:00",
                "2026-11-01T23:00:00+00:00",
            ),
            _record(
                "Vacances d'Été",
                "2027-07-02T22:00:00+00:00",
                "2027-09-01T22:00:00+00:00",
                population="Élèves",
            ),
            _record(
                "Vacances d'Été",
                "2027-07-02T22:00:00+00:00",
                "2027-08-31T22:00:00+00:00",
                population="Enseignants",
            ),
            _record(
                "Pont de l'Ascension",
                "2027-05-06T22:00:00+00:00",
                "2027-05-06T22:00:00+00:00",
            ),
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["refine.zones"] == "Zone A"
        return httpx.Response(200, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})

    client = OfficialSchoolVacationCalendarClient(transport=httpx.MockTransport(handler))
    periods = await client.fetch_periods(SchoolZone.A, date(2026, 1, 1), date(2027, 12, 31))

    assert [(period.name, period.start_date, period.end_date) for period in periods] == [
        ("Vacances de la Toussaint", date(2026, 10, 17), date(2026, 11, 1)),
        ("Vacances d'Été", date(2027, 7, 3), date(2027, 9, 1)),
    ]
