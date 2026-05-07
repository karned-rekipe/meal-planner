from datetime import date
from typing import Any

from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from domain.models.enums import SchoolZone, VacationPeriodSource
from domain.models.school_vacation_period import SchoolVacationPeriod
from domain.ports.output.school_vacation_period_repository import SchoolVacationPeriodRepository


class MongoDBSchoolVacationPeriodRepository(
    MongoDBRepository[SchoolVacationPeriod],
    SchoolVacationPeriodRepository,
):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        collection_config = MongoDBConfig(
            uri=config.uri,
            db_name=config.db_name,
            collection_name="school_vacation_periods",
        )
        super().__init__(collection_config, SchoolVacationPeriod, logger)

    def _to_doc(self, entity: SchoolVacationPeriod) -> dict[str, Any]:
        doc = entity.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        return doc

    async def find_for_date(
        self,
        target_date: date,
        school_zone: SchoolZone | None,
    ) -> list[SchoolVacationPeriod]:
        official_zone_match: dict[str, Any]
        if school_zone is None:
            official_zone_match = {"school_zone": None}
        else:
            official_zone_match = {"school_zone": {"$in": [school_zone.value, None]}}

        match = {
            "deleted_at": None,
            "start_date": {"$lte": target_date.isoformat()},
            "end_date": {"$gte": target_date.isoformat()},
            "$or": [
                {"source": VacationPeriodSource.MANUAL.value},
                {
                    "$and": [
                        {"source": VacationPeriodSource.OFFICIAL.value},
                        official_zone_match,
                    ],
                },
            ],
        }
        async with self._collection() as col:
            return [self._from_doc(doc) async for doc in col.find(match)]
