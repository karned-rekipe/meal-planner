from __future__ import annotations

import os
from typing import cast

from application.services.meal_plan_service import MealPlanService
from arclith import Arclith, AdapterRegistry
from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.domain.ports.logger import Logger
from arclith.domain.ports.repository import Repository
from arclith.infrastructure.config import AppConfig
from domain.models.household_member import HouseholdMember
from domain.models.household_schedule import HouseholdSchedule
from domain.models.meal_plan import MealPlan
from domain.models.school_vacation_period import SchoolVacationPeriod
from domain.models.tenant_preferences import TenantPreferences
from domain.ports.output.household_member_repository import HouseholdMemberRepository
from domain.ports.output.household_schedule_repository import HouseholdScheduleRepository
from domain.ports.output.meal_plan_repository import MealPlanRepository
from domain.ports.output.recipe_client import RecipeClient
from domain.ports.output.school_vacation_period_repository import SchoolVacationPeriodRepository
from domain.ports.output.tenant_preferences_repository import TenantPreferencesRepository


def _build_memory(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.memory.repository import InMemoryMealPlanRepository
    return InMemoryMealPlanRepository()


def _build_mongodb(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.mongodb.repository import MongoDBMealPlanRepository
    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBMealPlanRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name, collection_name=mongo.collection_name),
        log,
    )


def _build_duckdb(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.duckdb.repository import DuckDBMealPlanRepository
    duckdb = cfg.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")
    return DuckDBMealPlanRepository(duckdb.path)


def _build_memory_preferences(cfg: AppConfig, log: Logger) -> Repository[TenantPreferences]:
    from adapters.output.memory.repository import InMemoryTenantPreferencesRepository

    return InMemoryTenantPreferencesRepository()


def _build_memory_household_schedule(cfg: AppConfig, log: Logger) -> Repository[HouseholdSchedule]:
    from adapters.output.memory.repository import InMemoryHouseholdScheduleRepository

    return InMemoryHouseholdScheduleRepository()


def _build_memory_household_member(cfg: AppConfig, log: Logger) -> Repository[HouseholdMember]:
    from adapters.output.memory.repository import InMemoryHouseholdMemberRepository

    return InMemoryHouseholdMemberRepository()


def _build_memory_school_vacation_periods(cfg: AppConfig, log: Logger) -> Repository[SchoolVacationPeriod]:
    from adapters.output.memory.repository import InMemorySchoolVacationPeriodRepository

    return InMemorySchoolVacationPeriodRepository()


def _build_mongodb_preferences(cfg: AppConfig, log: Logger) -> Repository[TenantPreferences]:
    from adapters.output.mongodb.repository import MongoDBTenantPreferencesRepository

    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBTenantPreferencesRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name, collection_name="tenant_preferences"),
        log,
    )


def _build_mongodb_household_schedule(cfg: AppConfig, log: Logger) -> Repository[HouseholdSchedule]:
    from adapters.output.mongodb.repository import MongoDBHouseholdScheduleRepository

    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBHouseholdScheduleRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name, collection_name="household_schedules"),
        log,
    )


def _build_mongodb_household_member(cfg: AppConfig, log: Logger) -> Repository[HouseholdMember]:
    from adapters.output.mongodb.repository import MongoDBHouseholdMemberRepository

    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBHouseholdMemberRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name, collection_name="household_members"),
        log,
    )


def _build_mongodb_school_vacation_periods(cfg: AppConfig, log: Logger) -> Repository[SchoolVacationPeriod]:
    from adapters.output.mongodb.repository import MongoDBSchoolVacationPeriodRepository

    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBSchoolVacationPeriodRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name, collection_name="school_vacation_periods"),
        log,
    )


def _build_duckdb_household_schedule(cfg: AppConfig, log: Logger) -> Repository[HouseholdSchedule]:
    from adapters.output.duckdb.repository import DuckDBHouseholdScheduleRepository

    duckdb = cfg.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")
    return DuckDBHouseholdScheduleRepository(duckdb.path)


def _build_duckdb_school_vacation_periods(cfg: AppConfig, log: Logger) -> Repository[SchoolVacationPeriod]:
    from adapters.output.duckdb.repository import DuckDBSchoolVacationPeriodRepository

    duckdb = cfg.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")
    return DuckDBSchoolVacationPeriodRepository(duckdb.path)


_registry = cast(
    AdapterRegistry[MealPlan],
    AdapterRegistry[MealPlan]()
    .register("memory", _build_memory)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb)  # type: ignore[arg-type]
    .register("duckdb", _build_duckdb)  # type: ignore[arg-type]
)

_preferences_registry = cast(
    AdapterRegistry[TenantPreferences],
    AdapterRegistry[TenantPreferences]()
    .register("memory", _build_memory_preferences)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb_preferences)  # type: ignore[arg-type]
)

_household_schedule_registry = cast(
    AdapterRegistry[HouseholdSchedule],
    AdapterRegistry[HouseholdSchedule]()
    .register("memory", _build_memory_household_schedule)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb_household_schedule)  # type: ignore[arg-type]
    .register("duckdb", _build_duckdb_household_schedule)  # type: ignore[arg-type]
)

_household_member_registry = cast(
    AdapterRegistry[HouseholdMember],
    AdapterRegistry[HouseholdMember]()
    .register("memory", _build_memory_household_member)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb_household_member)  # type: ignore[arg-type]
)

_school_vacation_period_registry = cast(
    AdapterRegistry[SchoolVacationPeriod],
    AdapterRegistry[SchoolVacationPeriod]()
    .register("memory", _build_memory_school_vacation_periods)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb_school_vacation_periods)  # type: ignore[arg-type]
    .register("duckdb", _build_duckdb_school_vacation_periods)  # type: ignore[arg-type]
)


def _build_recipe_client() -> RecipeClient:
    from adapters.output.http.recipe_http_client import RecipeHttpClient
    from adapters.output.http.static_recipe_client import StaticRecipeClient

    base_url = os.getenv("RECIPE_BASE_URL")
    if not base_url:
        return StaticRecipeClient()
    return RecipeHttpClient(
        base_url=base_url,
        tenant_uri=os.getenv("REKIPE_TENANT_URI"),
        api_token=os.getenv("RECIPE_API_TOKEN"),
    )


def build_meal_plan_service(arclith: Arclith) -> tuple[MealPlanService, Logger]:
    arclith.logger.info("🗄️ Repository adapter selected", adapter=arclith.config.adapters.repository)
    repo: MealPlanRepository = cast(MealPlanRepository, _registry.build(arclith.config, arclith.logger))
    preferences_repo: TenantPreferencesRepository | None = None
    household_member_repo: HouseholdMemberRepository | None = None
    household_schedule_repo: HouseholdScheduleRepository | None = cast(
        HouseholdScheduleRepository,
        _household_schedule_registry.build(arclith.config, arclith.logger),
    )
    school_vacation_period_repo: SchoolVacationPeriodRepository | None = cast(
        SchoolVacationPeriodRepository,
        _school_vacation_period_registry.build(arclith.config, arclith.logger),
    )
    if arclith.config.adapters.repository in {"memory", "mongodb"}:
        preferences_repo = cast(
            TenantPreferencesRepository,
            _preferences_registry.build(arclith.config, arclith.logger),
        )
        household_member_repo = cast(
            HouseholdMemberRepository,
            _household_member_registry.build(arclith.config, arclith.logger),
        )
    return (
        MealPlanService(
            repo,
            arclith.logger,
            arclith.config.soft_delete.retention_days,
            recipe_client=_build_recipe_client(),
            tenant_preferences_repository=preferences_repo,
            household_schedule_repository=household_schedule_repo,
            household_member_repository=household_member_repo,
            school_vacation_period_repository=school_vacation_period_repo,
        ),
        arclith.logger,
    )
