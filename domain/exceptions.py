from uuid import UUID


class MealPlannerError(Exception):
    """Base class for meal-planner business errors."""


class MealPlanNotFound(MealPlannerError):
    """Raised when a meal plan does not exist or is deleted."""


class VersionConflict(MealPlannerError):
    """Raised when optimistic locking fails."""


class OverlapWithConfirmedPlan(MealPlannerError):
    def __init__(self, conflicts: list[UUID]) -> None:
        super().__init__("confirmed meal plan overlap")
        self.conflicts = conflicts


class InvalidStatusTransition(MealPlannerError):
    """Raised when the requested status transition is not allowed."""


class InvalidMealPlanOperation(MealPlannerError):
    """Raised when a business operation is forbidden for the current aggregate state."""


class RecipeNotFound(MealPlannerError):
    """Raised when a referenced recipe does not exist."""


class RecipeNotEligible(MealPlannerError):
    """Raised when a referenced recipe cannot be planned."""


class IngredientNotFound(MealPlannerError):
    """Raised when a referenced ingredient does not exist."""


class TenantPreferencesNotFound(MealPlannerError):
    """Raised when tenant preferences cannot be found."""


class SchoolVacationPeriodNotFound(MealPlannerError):
    """Raised when a school vacation period cannot be found."""
