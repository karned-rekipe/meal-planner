from datetime import date

from domain.models.enums import MealPlanStatus
from domain.models.meal_plan import MealPlan

DEFAULT_DATE_START = date(2026, 1, 5)
DEFAULT_DATE_END = date(2026, 1, 11)


def meal_plan(name: str = "Semaine test", **kwargs) -> MealPlan:
    return MealPlan(
        name=name,
        date_start=kwargs.pop("date_start", DEFAULT_DATE_START),
        date_end=kwargs.pop("date_end", DEFAULT_DATE_END),
        status=kwargs.pop("status", MealPlanStatus.DRAFT),
        **kwargs,
    )


def meal_plan_payload(name: str = "Semaine test", **kwargs) -> dict:
    return {
        "name": name,
        "date_start": kwargs.pop("date_start", DEFAULT_DATE_START).isoformat(),
        "date_end": kwargs.pop("date_end", DEFAULT_DATE_END).isoformat(),
        **kwargs,
    }
