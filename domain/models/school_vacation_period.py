from datetime import date

from pydantic import Field, model_validator

from arclith.domain.models.entity import Entity
from domain.models.enums import SchoolZone, VacationPeriodSource


class SchoolVacationPeriod(Entity):
    source: VacationPeriodSource
    school_zone: SchoolZone | None = None
    name: str = Field(..., min_length=1, max_length=120)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_period(self) -> "SchoolVacationPeriod":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self
