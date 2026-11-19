from typing import Any
from uuid import UUID

from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from domain.models.enums import DayOfWeek, SchoolPeriodType, SlotCode, WeekParity
from domain.models.household_schedule import HouseholdSchedule, HouseholdScheduleRule
from domain.ports.output.household_schedule_repository import HouseholdScheduleRepository


class MongoDBHouseholdScheduleRepository(
    MongoDBRepository[HouseholdSchedule],
    HouseholdScheduleRepository,
):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        collection_config = MongoDBConfig(
            uri=config.uri,
            db_name=config.db_name,
            collection_name="household_schedules",
        )
        super().__init__(collection_config, HouseholdSchedule, logger)

    def _to_doc(self, entity: HouseholdSchedule) -> dict[str, Any]:
        doc = entity.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        return doc

    async def get_singleton(self) -> HouseholdSchedule | None:
        async with self._collection() as col:
            doc = await col.find_one({"deleted_at": None})
        return self._from_doc(doc) if doc else None

    async def save_singleton(self, schedule: HouseholdSchedule) -> HouseholdSchedule:
        current = await self.get_singleton()
        async with self._collection() as col:
            if current is None:
                await col.insert_one(self._to_doc(schedule))
                return schedule
            updated = schedule.model_copy(update={"uuid": current.uuid})
            await col.replace_one({"_id": str(current.uuid)}, self._to_doc(updated))
            return updated

    async def list_rules(self, household_schedule_id: UUID) -> list[HouseholdScheduleRule]:
        async with self._collection() as col:
            docs = await col.database["household_schedule_rules"].find(
                {
                    "household_schedule_id": str(household_schedule_id),
                    "deleted_at": None,
                },
            ).to_list(length=None)
        rules = [self._rule_from_doc(doc) for doc in docs]
        rules.sort(key=lambda rule: (rule.week_parity, rule.school_period_type, rule.day_of_week, rule.meal_slot_code))
        return rules

    async def replace_rules(
        self,
        household_schedule_id: UUID,
        rules: list[HouseholdScheduleRule],
    ) -> list[HouseholdScheduleRule]:
        async with self._collection() as col:
            rules_col = col.database["household_schedule_rules"]
            await rules_col.delete_many({"household_schedule_id": str(household_schedule_id)})
            if rules:
                await rules_col.insert_many([
                    self._rule_to_doc(rule.model_copy(update={"household_schedule_id": household_schedule_id}))
                    for rule in rules
                ])
        return await self.list_rules(household_schedule_id)

    async def find_rule(
        self,
        household_schedule_id: UUID,
        *,
        week_parity: WeekParity,
        school_period_type: SchoolPeriodType,
        day_of_week: DayOfWeek,
        meal_slot_code: SlotCode,
    ) -> HouseholdScheduleRule | None:
        async with self._collection() as col:
            doc = await col.database["household_schedule_rules"].find_one({
                "household_schedule_id": str(household_schedule_id),
                "week_parity": week_parity.value,
                "school_period_type": school_period_type.value,
                "day_of_week": day_of_week.value,
                "meal_slot_code": meal_slot_code,
                "deleted_at": None,
            })
        return self._rule_from_doc(doc) if doc else None

    @staticmethod
    def _rule_to_doc(rule: HouseholdScheduleRule) -> dict[str, Any]:
        doc = rule.model_dump(mode="json", exclude_computed_fields=True)
        doc["_id"] = doc.pop("uuid")
        return doc

    @staticmethod
    def _rule_from_doc(doc: dict[str, Any]) -> HouseholdScheduleRule:
        payload = dict(doc)
        payload["uuid"] = payload.pop("_id")
        return HouseholdScheduleRule.model_validate(payload)
