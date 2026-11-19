from datetime import date, timedelta

from pydantic import Field, field_validator, model_validator

from arclith.domain.models.entity import Entity
from domain.models.enums import DEFAULT_SLOT_CODES, MealPlanStatus, SlotCode
from domain.models.meal_slot import MealSlot


class MealPlan(Entity):
    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Nom libre du plan",
        examples=["Semaine 17", "Vacances avril"],
    )
    status: MealPlanStatus = MealPlanStatus.DRAFT
    date_start: date
    date_end: date
    slots: list[MealSlot] = Field(default_factory=list)
    migration_metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("MealPlan name cannot be empty")
        return stripped

    @model_validator(mode="after")
    def validate_period(self) -> "MealPlan":
        if self.date_end < self.date_start:
            raise ValueError("date_end must be >= date_start")
        return self

    @model_validator(mode="after")
    def slots_match_period(self) -> "MealPlan":
        seen: set[tuple[date, SlotCode]] = set()
        for slot in self.slots:
            if not self.date_start <= slot.date <= self.date_end:
                raise ValueError(f"slot {slot.date} {slot.slot_code} outside plan period")
            key = (slot.date, slot.slot_code)
            if key in seen:
                raise ValueError(f"duplicate slot {key}")
            seen.add(key)
        return self

    @staticmethod
    def empty_slots_for_period(
        date_start: date,
        date_end: date,
        slot_codes: tuple[SlotCode, ...] = DEFAULT_SLOT_CODES,
    ) -> list[MealSlot]:
        return MealPlan._complete_slots_for_period([], date_start, date_end, slot_codes)

    def with_complete_empty_slots(self) -> "MealPlan":
        slots = self._complete_slots_for_period(self.slots, self.date_start, self.date_end)
        return self.model_copy(update={"slots": slots})

    @staticmethod
    def _complete_slots_for_period(
        slots: list[MealSlot],
        date_start: date,
        date_end: date,
        default_slot_codes: tuple[SlotCode, ...] = DEFAULT_SLOT_CODES,
    ) -> list[MealSlot]:
        existing = {(slot.date, slot.slot_code): slot for slot in slots}
        custom_slots_by_date: dict[date, list[MealSlot]] = {}
        for slot in slots:
            if date_start <= slot.date <= date_end and slot.slot_code not in default_slot_codes:
                custom_slots_by_date.setdefault(slot.date, []).append(slot)

        completed_slots: list[MealSlot] = []
        current = date_start
        while current <= date_end:
            for slot_code in default_slot_codes:
                completed_slots.append(
                    existing.get(
                        (current, slot_code),
                        MealSlot(date=current, slot_code=slot_code, headcount=None),
                    ),
                )
            completed_slots.extend(custom_slots_by_date.get(current, []))
            current += timedelta(days=1)
        return completed_slots
