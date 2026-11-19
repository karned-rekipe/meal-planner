from datetime import UTC, date, datetime, timedelta
from typing import Any

from arclith.adapters.context import get_adapter_tenant_context
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from adapters.input.fastapi.dependencies import inject_tenant_uri

Document = dict[str, Any]

_CLIENTS: dict[str, AsyncIOMotorClient] = {}
_DAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_LEGACY_SLOT_CODES: dict[str, str] = {
    "0": "breakfast",
    "1": "lunch",
    "2": "gouter",
    "3": "dinner",
}
_DEFAULT_MEAL_SLOTS: list[dict[str, str | int]] = [
    {"code": "breakfast", "label": "Petit déjeuner", "position": 0},
    {"code": "lunch", "label": "Déjeuner", "position": 1},
    {"code": "gouter", "label": "Goûter", "position": 2},
    {"code": "dinner", "label": "Dîner", "position": 3},
]


class TenantPlanningRouter:
    def __init__(self) -> None:
        self.router = APIRouter(
            prefix="/v1",
            tags=["tenant-planning"],
            dependencies=[Depends(inject_tenant_uri)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route(
            methods=["GET"],
            path="/meal-plans/calendar",
            endpoint=self.get_calendar,
            status_code=200,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/tenant-preferences/",
            endpoint=self.get_tenant_preferences,
            status_code=200,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/household-members/",
            endpoint=self.list_household_members,
            status_code=200,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/household-schedule/",
            endpoint=self.get_household_schedule,
            status_code=200,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/school-vacation-periods/",
            endpoint=self.list_school_vacation_periods,
            status_code=200,
        )

    async def get_calendar(
        self,
        response: Response,
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
    ) -> dict[str, Any]:
        db = _tenant_db()
        start, end = await _resolve_calendar_period(db, date_from, date_to)
        entries = await _active_entries(db, start, end)
        preferences = await _tenant_preferences(db)
        schedule = await _household_schedule(db)
        rules = await _household_schedule_rules(db, schedule["_id"])
        recipe_snapshots = await _recipe_snapshots(db, entries)
        ingredient_snapshots = await _ingredient_snapshots(db, entries)

        slots = _calendar_slots(
            start=start,
            end=end,
            meal_slots=preferences["meal_slots"],
            schedule_mode=schedule["schedule_mode"],
            rules=rules,
            entries=entries,
            recipe_snapshots=recipe_snapshots,
            ingredient_snapshots=ingredient_snapshots,
        )
        updated_at = _max_updated_at(entries, schedule)
        plan = {
            "uuid": f"legacy-calendar-{start.isoformat()}-{end.isoformat()}",
            "version": 1,
            "created_at": updated_at,
            "updated_at": updated_at,
            "name": "Planning legacy",
            "status": "draft",
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "slots": slots,
            "migration_metadata": {
                "source_collection": "meal_plan_entry",
                "fallback_latest_data": date_from is not None and not await _has_entries_in_requested_range(db, date_from, date_to),
            },
        }
        response.headers["ETag"] = '"1"'
        return _success(plan)

    async def get_tenant_preferences(self, response: Response) -> dict[str, Any]:
        preferences = await _tenant_preferences(_tenant_db())
        response.headers["ETag"] = f'"{preferences["version"]}"'
        return _success(_tenant_preferences_payload(preferences))

    async def list_household_members(self) -> dict[str, Any]:
        members = await _tenant_db().household_members.find({"deleted_at": None}).sort("name", 1).to_list(length=None)
        return _success([_household_member_payload(member) for member in members])

    async def get_household_schedule(self, response: Response) -> dict[str, Any]:
        db = _tenant_db()
        schedule = await _household_schedule(db)
        rules = await _household_schedule_rules(db, schedule["_id"])
        payload = _household_schedule_payload(schedule, rules)
        response.headers["ETag"] = f'"{payload["version"]}"'
        return _success(payload)

    async def list_school_vacation_periods(self) -> dict[str, Any]:
        periods = await _tenant_db().school_vacation_periods.find({"deleted_at": None}).sort("start_date", 1).to_list(length=None)
        return _success([_document_payload(period) for period in periods])


def _tenant_db() -> AsyncIOMotorDatabase:
    coords = get_adapter_tenant_context("mongodb")
    if coords is None:
        raise HTTPException(status_code=401, detail="Tenant MongoDB non résolu")

    uri = coords.get("uri")
    db_name = coords.get("db_name")
    if not uri or not db_name:
        raise HTTPException(status_code=500, detail="Coordonnées MongoDB tenant incomplètes")

    client = _CLIENTS.get(uri)
    if client is None:
        client = AsyncIOMotorClient(uri)
        _CLIENTS[uri] = client
    return client[db_name]


async def _resolve_calendar_period(db: AsyncIOMotorDatabase, raw_start: str | None, raw_end: str | None) -> tuple[date, date]:
    requested_start = _date_from_iso(raw_start)
    requested_end = _date_from_iso(raw_end)
    if requested_start and requested_end and requested_start > requested_end:
        raise HTTPException(status_code=422, detail="date_from doit précéder date_to")

    start = requested_start or _today()
    end = requested_end or (start + timedelta(days=28))
    if await _entries_collection(db).count_documents(_date_filter(start, end, limit_to_active=True)):
        return start, end

    latest = await _latest_entry_date(db)
    if latest is None:
        return start, end

    requested_span = max((end - start).days, 0)
    span = min(requested_span or 28, 56)
    return latest - timedelta(days=span), latest


async def _has_entries_in_requested_range(db: AsyncIOMotorDatabase, raw_start: str | None, raw_end: str | None) -> bool:
    start = _date_from_iso(raw_start)
    end = _date_from_iso(raw_end)
    if not start or not end:
        return False
    return bool(await _entries_collection(db).count_documents(_date_filter(start, end, limit_to_active=True)))


async def _latest_entry_date(db: AsyncIOMotorDatabase) -> date | None:
    docs = await _entries_collection(db).find({"date": {"$type": "string"}, "status": "active"}).sort("date", -1).limit(1).to_list(length=1)
    if not docs:
        return None
    return _date_from_iso(docs[0].get("date"))


async def _active_entries(db: AsyncIOMotorDatabase, start: date, end: date) -> list[Document]:
    return await _entries_collection(db).find(_date_filter(start, end, limit_to_active=True)).sort(
        [("date", 1), ("meal_slot_code_legacy", 1), ("legacy_rank", 1), ("created_at", 1)]
    ).to_list(length=None)


async def _tenant_preferences(db: AsyncIOMotorDatabase) -> Document:
    preferences = await db.tenant_preferences.find_one({"deleted_at": None}, sort=[("updated_at", -1)])
    if preferences is None:
        return {
            "_id": "tenant-preferences-default",
            "version": 1,
            "exclusions": {"ingredients": [], "groups": []},
            "favorites": {"recipes": []},
            "meal_slots": _DEFAULT_MEAL_SLOTS,
        }
    meal_slots = preferences.get("meal_slots")
    if not isinstance(meal_slots, list) or not meal_slots:
        preferences["meal_slots"] = _DEFAULT_MEAL_SLOTS
    return preferences


async def _household_schedule(db: AsyncIOMotorDatabase) -> Document:
    schedule = await db.household_schedules.find_one({"deleted_at": None}, sort=[("updated_at", -1)])
    if schedule is None:
        return {
            "_id": "household-schedule-default",
            "version": 1,
            "school_zone": None,
            "schedule_mode": "headcount",
        }
    return schedule


async def _household_schedule_rules(db: AsyncIOMotorDatabase, schedule_id: str) -> list[Document]:
    return await db.household_schedule_rules.find(
        {"deleted_at": None, "household_schedule_id": str(schedule_id)}
    ).to_list(length=None)


async def _recipe_snapshots(db: AsyncIOMotorDatabase, entries: list[Document]) -> dict[str, Document]:
    recipe_ids = sorted({entry["recipe_uuid"] for entry in entries if entry.get("recipe_uuid")})
    if not recipe_ids:
        return {}
    recipes = await db.recipe.find({"_id": {"$in": recipe_ids}}).to_list(length=None)
    return {str(recipe["_id"]): recipe for recipe in recipes}


async def _ingredient_snapshots(db: AsyncIOMotorDatabase, entries: list[Document]) -> dict[str, Document]:
    ingredient_ids = sorted({entry["ingredient_uuid"] for entry in entries if entry.get("ingredient_uuid")})
    if not ingredient_ids:
        return {}
    ingredients = await db.ingredient.find({"_id": {"$in": ingredient_ids}}).to_list(length=None)
    return {str(ingredient["_id"]): ingredient for ingredient in ingredients}


def _entries_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:
    return db.meal_plan_entry


def _date_filter(start: date, end: date, *, limit_to_active: bool) -> dict[str, Any]:
    query: dict[str, Any] = {"date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}
    if limit_to_active:
        query["status"] = "active"
    return query


def _calendar_slots(
    *,
    start: date,
    end: date,
    meal_slots: list[Document],
    schedule_mode: str,
    rules: list[Document],
    entries: list[Document],
    recipe_snapshots: dict[str, Document],
    ingredient_snapshots: dict[str, Document],
) -> list[dict[str, Any]]:
    slots_by_key = _scheduled_slots(start, end, meal_slots, schedule_mode, rules)
    for entry in entries:
        slot_code = _slot_code_from_entry(entry)
        if slot_code is None:
            continue
        slot_date = entry.get("date")
        if not isinstance(slot_date, str):
            continue
        key = (slot_date, slot_code)
        slot = slots_by_key.setdefault(key, _empty_slot(slot_date, slot_code))
        item = _meal_item_from_entry(entry, slot, recipe_snapshots, ingredient_snapshots)
        if item is not None:
            slot["items"].append(item)

    for slot in slots_by_key.values():
        slot["items"].sort(key=lambda item: item["position"])
    return sorted(slots_by_key.values(), key=lambda slot: (slot["date"], _slot_position(slot["slot_code"], meal_slots)))


def _scheduled_slots(
    start: date,
    end: date,
    meal_slots: list[Document],
    schedule_mode: str,
    rules: list[Document],
) -> dict[tuple[str, str], dict[str, Any]]:
    rules_by_key = {
        (
            str(rule.get("week_parity")),
            str(rule.get("school_period_type")),
            str(rule.get("day_of_week")),
            str(rule.get("meal_slot_code")),
        ): rule
        for rule in rules
    }
    slots: dict[tuple[str, str], dict[str, Any]] = {}
    current = start
    while current <= end:
        iso_week = current.isocalendar().week
        week_parity = "even" if iso_week % 2 == 0 else "odd"
        day_name = _DAY_NAMES[current.weekday()]
        for meal_slot in meal_slots:
            slot_code = str(meal_slot.get("code", ""))
            if not slot_code:
                continue
            slot = _empty_slot(current.isoformat(), slot_code)
            rule = rules_by_key.get((week_parity, "regular", day_name, slot_code))
            if rule is not None:
                member_ids = [str(member_id) for member_id in rule.get("member_ids", [])]
                slot["member_ids"] = member_ids if schedule_mode == "members" else []
                slot["headcount"] = len(member_ids) if schedule_mode == "members" and member_ids else rule.get("headcount")
                slot["headcount_source"] = "household_schedule"
            slots[(slot["date"], slot_code)] = slot
        current += timedelta(days=1)
    return slots


def _meal_item_from_entry(
    entry: Document,
    slot: dict[str, Any],
    recipe_snapshots: dict[str, Document],
    ingredient_snapshots: dict[str, Document],
) -> dict[str, Any] | None:
    item_type = _item_type_from_entry(entry)
    if item_type is None:
        return None

    recipe_uuid = _optional_str(entry.get("recipe_uuid"))
    ingredient_uuid = _optional_str(entry.get("ingredient_uuid"))
    recipe = recipe_snapshots.get(recipe_uuid or "")
    ingredient = ingredient_snapshots.get(ingredient_uuid or "")
    headcount = entry.get("headcount") or slot.get("headcount")
    member_ids = list(slot.get("member_ids", []))
    position = _position_from_entry(entry, len(slot["items"]))
    note = _optional_str(entry.get("note"))

    item: dict[str, Any] = {
        "uuid": str(entry["_id"]),
        "position": position,
        "item_type": item_type,
        "headcount": headcount,
        "member_ids": member_ids,
        "recipe_uuid": recipe_uuid if item_type == "recipe" else None,
        "recipe_snapshot": _recipe_snapshot(recipe, recipe_uuid, headcount) if item_type == "recipe" else None,
        "recipe_status": recipe.get("status") if recipe else None,
        "recipe_modified": False,
        "ingredient_uuid": ingredient_uuid if item_type == "ingredient" else None,
        "ingredient_name": _ingredient_name(ingredient, ingredient_uuid) if item_type == "ingredient" else None,
        "ingredient_quantity": 1 if item_type == "ingredient" else None,
        "ingredient_unit": _optional_str(ingredient.get("unit")) if ingredient else None,
        "note": note,
        "legacy_id": entry.get("legacy_id"),
    }
    return item


def _item_type_from_entry(entry: Document) -> str | None:
    entry_type = entry.get("entry_type")
    if entry_type == "mixed":
        if entry.get("recipe_uuid"):
            return "recipe"
        if entry.get("ingredient_uuid"):
            return "ingredient"
        if entry.get("note"):
            return "note"
        return "mixed"
    if entry_type in {"recipe", "ingredient", "note", "prep_task"}:
        return str(entry_type)
    return None


def _slot_code_from_entry(entry: Document) -> str | None:
    raw_code = entry.get("meal_slot_code_legacy")
    if raw_code is None:
        return None
    return _LEGACY_SLOT_CODES.get(str(raw_code))


def _empty_slot(slot_date: str, slot_code: str) -> dict[str, Any]:
    return {
        "date": slot_date,
        "slot_code": slot_code,
        "headcount": None,
        "headcount_source": None,
        "member_ids": [],
        "items": [],
    }


def _recipe_snapshot(recipe: Document | None, recipe_uuid: str | None, headcount: int | None) -> dict[str, Any] | None:
    if recipe_uuid is None:
        return None
    servings = recipe.get("servings") if recipe else None
    if not isinstance(servings, int) or servings <= 0:
        servings = headcount if isinstance(headcount, int) and headcount > 0 else 1
    return {
        "recipe_uuid": recipe_uuid,
        "title": _optional_str(recipe.get("name")) if recipe else "Recette",
        "short_description": _optional_str(recipe.get("description")) if recipe else None,
        "servings_default": servings,
        "total_duration_min": recipe.get("total_duration_min") if recipe else None,
        "ingredients": [],
        "snapshot_taken_at": _now_iso(),
        "recipe_version": recipe.get("version") if recipe else None,
    }


def _ingredient_name(ingredient: Document | None, ingredient_uuid: str | None) -> str | None:
    if ingredient is None:
        return ingredient_uuid
    return _optional_str(ingredient.get("name")) or ingredient_uuid


def _tenant_preferences_payload(preferences: Document) -> dict[str, Any]:
    return {
        "uuid": str(preferences["_id"]),
        "version": preferences.get("version", 1),
        "exclusions": preferences.get("exclusions", {"ingredients": [], "groups": []}),
        "favorites": preferences.get("favorites", {"recipes": []}),
        "meal_slots": preferences.get("meal_slots", _DEFAULT_MEAL_SLOTS),
    }


def _household_member_payload(member: Document) -> dict[str, Any]:
    return {
        "uuid": str(member["_id"]),
        "version": member.get("version", 1),
        "name": member.get("name", ""),
        "member_type": member.get("member_type", "resident"),
        "gender": member.get("gender"),
        "birth_year": member.get("birth_year"),
        "avatar_data": member.get("avatar_data"),
        "color": member.get("color", "#64748b"),
    }


def _household_schedule_payload(schedule: Document, rules: list[Document]) -> dict[str, Any]:
    return {
        "uuid": str(schedule["_id"]),
        "version": schedule.get("version", 1),
        "school_zone": schedule.get("school_zone"),
        "schedule_mode": schedule.get("schedule_mode", "headcount"),
        "rules": [_document_payload(rule) for rule in rules],
    }


def _document_payload(document: Document) -> dict[str, Any]:
    payload = {key: value for key, value in document.items() if key != "_id"}
    payload["uuid"] = str(document["_id"])
    payload.setdefault("version", 1)
    return payload


def _success(data: Any) -> dict[str, Any]:
    return {
        "status": "success",
        "data": data,
        "metadata": {
            "timestamp": _now_iso(),
            "version": "v1",
        },
    }


def _date_from_iso(value: str | None) -> date | None:
    if value is None or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Date invalide: {value}") from exc


def _today() -> date:
    return datetime.now(UTC).date()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _max_updated_at(entries: list[Document], fallback: Document) -> str:
    values = [_optional_str(entry.get("updated_at")) for entry in entries]
    values.append(_optional_str(fallback.get("updated_at")))
    return max(value for value in values if value) if any(values) else _now_iso()


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _position_from_entry(entry: Document, fallback: int) -> int:
    rank = entry.get("legacy_rank")
    if isinstance(rank, int):
        return rank
    if isinstance(rank, str) and rank.isdecimal():
        return int(rank)
    return fallback


def _slot_position(slot_code: str, meal_slots: list[Document]) -> int:
    for index, meal_slot in enumerate(meal_slots):
        if meal_slot.get("code") == slot_code:
            position = meal_slot.get("position")
            return position if isinstance(position, int) else index
    return len(meal_slots)
