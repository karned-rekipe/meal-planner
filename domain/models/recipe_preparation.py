from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from domain.models.enums import PreparationTimerStatus


MAX_TIMER_SECONDS = 7 * 24 * 60 * 60


class RecipePreparationTimer(BaseModel):
    timer_id: str = Field(..., min_length=1, max_length=200)
    duration_seconds: int = Field(..., ge=1, le=MAX_TIMER_SECONDS)
    remaining_seconds: int = Field(..., ge=0, le=MAX_TIMER_SECONDS)
    status: PreparationTimerStatus
    started_at: datetime | None = None
    ringing_since: datetime | None = None

    @field_validator("timer_id", mode="before")
    @classmethod
    def strip_timer_id(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_timer_state(self) -> "RecipePreparationTimer":
        if self.remaining_seconds > self.duration_seconds:
            raise ValueError("remaining_seconds cannot exceed duration_seconds")
        if self.status == PreparationTimerStatus.RUNNING and self.started_at is None:
            raise ValueError("running timer requires started_at")
        if self.status != PreparationTimerStatus.RUNNING and self.started_at is not None:
            raise ValueError("only a running timer may have started_at")
        if self.status != PreparationTimerStatus.RINGING and self.ringing_since is not None:
            raise ValueError("only a ringing timer may have ringing_since")
        if self.status in (PreparationTimerStatus.RINGING, PreparationTimerStatus.COMPLETED):
            if self.remaining_seconds != 0:
                raise ValueError("ringing or completed timer requires zero remaining_seconds")
        return self


class RecipePreparationProgress(BaseModel):
    target_servings: int = Field(..., ge=1, le=99)
    completed_ingredient_ids: list[str] = Field(default_factory=list, max_length=500)
    completed_equipment_ids: list[str] = Field(default_factory=list, max_length=200)
    completed_step_ids: list[str] = Field(default_factory=list, max_length=200)
    timers: list[RecipePreparationTimer] = Field(default_factory=list, max_length=100)

    @field_validator(
        "completed_ingredient_ids",
        "completed_equipment_ids",
        "completed_step_ids",
        mode="after",
    )
    @classmethod
    def normalize_completed_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in normalized):
            raise ValueError("completed preparation identifiers must contain 1 to 200 characters")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def timers_must_be_unique(self) -> "RecipePreparationProgress":
        timer_ids = [timer.timer_id for timer in self.timers]
        if len(timer_ids) != len(set(timer_ids)):
            raise ValueError("timer_id values must be unique")
        return self
