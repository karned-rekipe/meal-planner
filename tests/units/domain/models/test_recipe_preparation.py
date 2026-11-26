from datetime import datetime, timezone

import pytest

from domain.models.enums import MealItemType
from domain.models.meal_item import MealItem
from domain.models.recipe_preparation import RecipePreparationProgress, RecipePreparationTimer


def test_recipe_preparation_progress_deduplicates_completed_ids():
    progress = RecipePreparationProgress(
        target_servings=6,
        completed_ingredient_ids=["ingredient:a:0", "ingredient:a:0"],
    )

    assert progress.completed_ingredient_ids == ["ingredient:a:0"]


def test_running_timer_requires_a_start_time():
    with pytest.raises(ValueError, match="requires started_at"):
        RecipePreparationTimer(
            timer_id="step:1:cooking",
            duration_seconds=180,
            remaining_seconds=180,
            status="running",
        )


def test_running_timer_preserves_initial_and_remaining_duration():
    timer = RecipePreparationTimer(
        timer_id="step:1:cooking",
        duration_seconds=180,
        remaining_seconds=45,
        status="running",
        started_at=datetime.now(timezone.utc),
    )

    assert timer.duration_seconds == 180
    assert timer.remaining_seconds == 45


def test_ringing_timer_preserves_when_alarm_started():
    ringing_since = datetime(2026, 11, 26, 18, 3, tzinfo=timezone.utc)

    timer = RecipePreparationTimer(
        timer_id="step:1:cooking",
        duration_seconds=180,
        remaining_seconds=0,
        status="ringing",
        ringing_since=ringing_since,
    )

    assert timer.ringing_since == ringing_since


def test_non_ringing_timer_rejects_ringing_start_time():
    with pytest.raises(ValueError, match="only a ringing timer may have ringing_since"):
        RecipePreparationTimer(
            timer_id="step:1:cooking",
            duration_seconds=180,
            remaining_seconds=45,
            status="paused",
            ringing_since=datetime.now(timezone.utc),
        )


def test_legacy_ringing_timer_without_start_time_remains_readable():
    timer = RecipePreparationTimer(
        timer_id="step:1:cooking",
        duration_seconds=180,
        remaining_seconds=0,
        status="ringing",
    )

    assert timer.ringing_since is None


def test_non_recipe_item_rejects_preparation_progress():
    with pytest.raises(ValueError, match="only available for recipe items"):
        MealItem(
            position=0,
            item_type=MealItemType.NOTE,
            note="Mettre la table",
            preparation_progress=RecipePreparationProgress(target_servings=2),
        )
