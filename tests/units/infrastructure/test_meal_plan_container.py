import pytest
from application.services.meal_plan_service import MealPlanService
from arclith.infrastructure.config import (
    AppConfig,
    AdaptersSettings,
    MongoDBSettings,
    DuckDBSettings,
)
from infrastructure.containers.meal_plan_container import build_meal_plan_service
from unittest.mock import MagicMock


def _arclith(config: AppConfig, logger):
    mock = MagicMock()
    mock.config = config
    mock.logger = logger
    return mock


def test_memory_creates_service(logger):
    arclith = _arclith(AppConfig(adapters = AdaptersSettings(repository = "memory")), logger)
    service, log = build_meal_plan_service(arclith)
    assert isinstance(service, MealPlanService)
    assert log is logger


def test_mongodb_creates_service(logger):
    config = AppConfig(adapters = AdaptersSettings(
        repository = "mongodb",
        mongodb = MongoDBSettings(uri = "mongodb://localhost:27017", db_name = "test"),
    ))
    service, log = build_meal_plan_service(_arclith(config, logger))
    assert isinstance(service, MealPlanService)


def test_duckdb_creates_service(logger, tmp_path):
    config = AppConfig(adapters = AdaptersSettings(
        repository = "duckdb",
        duckdb = DuckDBSettings(path = str(tmp_path) + "/"),
    ))
    service, log = build_meal_plan_service(_arclith(config, logger))
    assert isinstance(service, MealPlanService)


def test_mongodb_missing_config_raises(logger):
    mock = MagicMock()
    mock.config.adapters.repository = "mongodb"
    mock.config.adapters.mongodb = None
    mock.logger = logger
    with pytest.raises(RuntimeError, match = "MongoDB"):
        build_meal_plan_service(mock)


def test_duckdb_missing_config_raises(logger):
    mock = MagicMock()
    mock.config.adapters.repository = "duckdb"
    mock.config.adapters.duckdb = None
    mock.logger = logger
    with pytest.raises(RuntimeError, match = "DuckDB"):
        build_meal_plan_service(mock)
