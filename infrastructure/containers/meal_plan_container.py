from __future__ import annotations

from typing import cast

from application.services.meal_plan_service import MealPlanService
from arclith import Arclith, AdapterRegistry
from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.domain.ports.logger import Logger
from arclith.domain.ports.repository import Repository
from arclith.infrastructure.config import AppConfig
from domain.models.meal_plan import MealPlan
from domain.ports.output.meal_plan_repository import MealPlanRepository


def _build_memory(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.memory.repository import InMemoryMealPlanRepository
    return InMemoryMealPlanRepository()


def _build_mongodb(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.mongodb.repository import MongoDBMealPlanRepository
    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDBMealPlanRepository(
        MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name),
        log,
    )


def _build_duckdb(cfg: AppConfig, log: Logger) -> Repository[MealPlan]:
    from adapters.output.duckdb.repository import DuckDBMealPlanRepository
    duckdb = cfg.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")
    return DuckDBMealPlanRepository(duckdb.path)


_registry = cast(
    AdapterRegistry[MealPlan],
    AdapterRegistry[MealPlan]()
    .register("memory", _build_memory)  # type: ignore[arg-type]
    .register("mongodb", _build_mongodb)  # type: ignore[arg-type]
    .register("duckdb", _build_duckdb)  # type: ignore[arg-type]
)


def build_meal_plan_service(arclith: Arclith) -> tuple[MealPlanService, Logger]:
    arclith.logger.info("🗄️ Repository adapter selected", adapter=arclith.config.adapters.repository)
    repo: MealPlanRepository = cast(MealPlanRepository, _registry.build(arclith.config, arclith.logger))
    return MealPlanService(repo, arclith.logger, arclith.config.soft_delete.retention_days), arclith.logger
