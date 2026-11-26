from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from adapters.input.fastapi.dependencies import inject_tenant_uri, require_auth
from adapters.input.fastapi.routers import (
    AdminRouter,
    HouseholdMemberRouter,
    HouseholdScheduleRouter,
    MealPlanRouter,
    TenantPreferencesRouter,
)
from adapters.output.memory.repository import (
    InMemoryHouseholdMemberRepository,
    InMemoryHouseholdScheduleRepository,
    InMemorySchoolVacationPeriodRepository,
    InMemoryTenantPreferencesRepository,
)
from adapters.output.http.static_recipe_client import StaticRecipeClient
from application.services.meal_plan_service import MealPlanService
from domain.models.enums import VacationPeriodSource
from domain.models.school_vacation_period import SchoolVacationPeriod
from infrastructure.purge_registry import PurgeRegistry
from tests.units.factories import DEFAULT_DATE_END, DEFAULT_DATE_START, meal_plan_payload


def _payload(**kwargs) -> dict:
    name = kwargs.pop("name", "Semaine test")
    return meal_plan_payload(name, **kwargs)


class FakeSchoolVacationCalendarClient:
    async def fetch_periods(self, school_zone, date_start, date_end):
        return [
            SchoolVacationPeriod(
                source=VacationPeriodSource.OFFICIAL,
                school_zone=school_zone,
                name="Vacances officielles",
                start_date=date(2027, 2, 13),
                end_date=date(2027, 2, 28),
            )
        ]


def _etag(response) -> str:
    value = response.headers.get("etag")
    assert value
    return value


@pytest.fixture
def service(repo, logger):
    return MealPlanService(
        repo,
        logger,
        recipe_client=StaticRecipeClient(),
        household_member_repository=InMemoryHouseholdMemberRepository(),
        tenant_preferences_repository=InMemoryTenantPreferencesRepository(),
        household_schedule_repository=InMemoryHouseholdScheduleRepository(),
        school_vacation_period_repository=InMemorySchoolVacationPeriodRepository(),
        school_vacation_calendar_client=FakeSchoolVacationCalendarClient(),
    )


@pytest.fixture
def app(service, logger):
    fastapi_app = FastAPI()
    registry = PurgeRegistry()
    registry.register("meal_plans", service.purge)
    fastapi_app.include_router(MealPlanRouter(service, logger).router)
    fastapi_app.include_router(TenantPreferencesRouter(service, logger).router)
    fastapi_app.include_router(HouseholdMemberRouter(service, logger).router)
    fastapi_app.include_router(HouseholdScheduleRouter(service, logger).router)
    fastapi_app.include_router(AdminRouter(registry).router)
    fastapi_app.dependency_overrides[inject_tenant_uri] = lambda: None
    fastapi_app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}
    return fastapi_app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def created(client):
    response = await client.post("/v1/meal-plans/", json=_payload())
    return {"data": response.json()["data"], "etag": _etag(response)}


def _replace_payload(plan: dict, **kwargs) -> dict:
    return {
        "name": kwargs.get("name", plan["name"]),
        "date_start": kwargs.get("date_start", plan["date_start"]),
        "date_end": kwargs.get("date_end", plan["date_end"]),
        "status": kwargs.get("status", plan["status"]),
        "slots": kwargs.get("slots", plan["slots"]),
    }


async def _set_meal_slots(client: AsyncClient, meal_slots: list[dict]) -> None:
    current = await client.get("/v1/tenant-preferences/")
    assert current.status_code == 200
    payload = current.json()["data"]
    response = await client.put(
        "/v1/tenant-preferences/",
        json={
            "exclusions": payload["exclusions"],
            "favorites": payload["favorites"],
            "meal_slots": meal_slots,
        },
        headers={"If-Match": _etag(current)},
    )
    assert response.status_code == 200


async def _set_household_schedule(client: AsyncClient, rules: list[dict], school_zone: str | None = "A") -> None:
    member_ids = []
    for index in range(max((int(rule.get("headcount", 0)) for rule in rules), default=0)):
        response = await client.post(
            "/v1/household-members/",
            json={
                "name": f"Personne {index + 1}",
                "member_type": "resident",
                "gender": None,
                "birth_year": None,
                "color": "#4a90d9",
            },
        )
        assert response.status_code == 201
        member_ids.append(response.json()["data"]["uuid"])
    named_rules = [
        {
            **{key: value for key, value in rule.items() if key != "headcount"},
            "member_ids": member_ids[: int(rule.get("headcount", 0))],
        }
        for rule in rules
    ]
    current = await client.get("/v1/household-schedule/")
    assert current.status_code == 200
    response = await client.put(
        "/v1/household-schedule/",
        json={"school_zone": school_zone, "schedule_mode": "members", "rules": named_rules},
        headers={"If-Match": _etag(current)},
    )
    assert response.status_code == 200


async def test_create_returns_201(client):
    response = await client.post("/v1/meal-plans/", json=_payload())
    assert response.status_code == 201


async def test_create_returns_full_plan(client):
    response = await client.post("/v1/meal-plans/", json=_payload(name="Semaine V3"))
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["name"] == "Semaine V3"
    assert len(data["data"]["slots"]) == 14
    assert response.headers.get("etag") == 'W/"1"'


async def test_create_uses_household_schedule_headcount(client):
    await _set_household_schedule(
        client,
        [
            {
                "week_parity": "even",
                "school_period_type": "regular",
                "day_of_week": "monday",
                "meal_slot_code": "lunch",
                "headcount": 4,
            }
        ],
    )

    response = await client.post(
        "/v1/meal-plans/",
        json=_payload(date_start=date(2026, 1, 5), date_end=date(2026, 1, 5)),
    )

    assert response.status_code == 201
    lunch = next(slot for slot in response.json()["data"]["slots"] if slot["slot_code"] == "lunch")
    assert lunch["headcount"] == 4
    assert lunch["headcount_source"] == "household_schedule"


async def test_manual_vacation_period_switches_household_schedule_template(client):
    await _set_household_schedule(
        client,
        [
            {
                "week_parity": "even",
                "school_period_type": "vacation",
                "day_of_week": "monday",
                "meal_slot_code": "lunch",
                "headcount": 6,
            }
        ],
    )
    vacation_response = await client.post(
        "/v1/school-vacation-periods/",
        json={
            "source": "manual",
            "school_zone": None,
            "name": "Vacances manuelles",
            "start_date": "2026-01-05",
            "end_date": "2026-01-11",
        },
    )
    assert vacation_response.status_code == 201

    response = await client.post(
        "/v1/meal-plans/",
        json=_payload(date_start=date(2026, 1, 5), date_end=date(2026, 1, 5)),
    )

    lunch = next(slot for slot in response.json()["data"]["slots"] if slot["slot_code"] == "lunch")
    assert lunch["headcount"] == 6
    assert lunch["headcount_source"] == "household_schedule"


async def test_school_vacation_period_crud(client):
    create_response = await client.post(
        "/v1/school-vacation-periods/",
        json={
            "source": "manual",
            "school_zone": None,
            "name": "Vacances manuelles",
            "start_date": "2026-01-05",
            "end_date": "2026-01-11",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()["data"]

    list_response = await client.get("/v1/school-vacation-periods/")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["uuid"] == created["uuid"]

    update_response = await client.put(
        f"/v1/school-vacation-periods/{created['uuid']}",
        json={
            "source": "manual",
            "school_zone": None,
            "name": "Vacances ajustées",
            "start_date": "2026-01-06",
            "end_date": "2026-01-12",
        },
        headers={"If-Match": _etag(create_response)},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["name"] == "Vacances ajustées"

    delete_response = await client.delete(
        f"/v1/school-vacation-periods/{created['uuid']}",
        headers={"If-Match": _etag(update_response)},
    )
    assert delete_response.status_code == 204
    assert (await client.get("/v1/school-vacation-periods/")).json()["data"] == []


async def test_school_zone_and_official_vacation_sync(client):
    schedule_response = await client.get("/v1/household-schedule/")
    zone_response = await client.put(
        "/v1/household-schedule/school-zone",
        json={"school_zone": "B"},
        headers={"If-Match": _etag(schedule_response)},
    )
    assert zone_response.status_code == 200
    assert zone_response.json()["data"]["school_zone"] == "B"

    sync_response = await client.post(
        "/v1/school-vacation-periods/sync-official",
        json={"date_start": "2027-01-01", "date_end": "2027-12-31"},
    )

    assert sync_response.status_code == 200
    result = sync_response.json()["data"]
    assert result["school_zone"] == "B"
    assert result["created"] == 1
    assert result["periods"][0]["source"] == "official"


async def test_household_schedule_rejects_undeclared_meal_slot(client):
    current = await client.get("/v1/household-schedule/")
    response = await client.put(
        "/v1/household-schedule/",
        json={
            "school_zone": "A",
            "rules": [
                {
                    "week_parity": "even",
                    "school_period_type": "regular",
                    "day_of_week": "monday",
                    "meal_slot_code": "snack",
                    "headcount": 2,
                }
            ],
        },
        headers={"If-Match": _etag(current)},
    )

    assert response.status_code == 422


async def test_get_found(client, created):
    uuid = created["data"]["uuid"]
    response = await client.get(f"/v1/meal-plans/{uuid}")
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Semaine test"


async def test_get_not_found(client):
    response = await client.get("/v1/meal-plans/01951234-5678-7abc-def0-000000000000")
    assert response.status_code == 404


async def test_update_requires_if_match(client, created):
    uuid = created["data"]["uuid"]
    response = await client.put(f"/v1/meal-plans/{uuid}", json=_replace_payload(created["data"]))
    assert response.status_code == 412


async def test_update_reflects_on_get(client, created):
    uuid = created["data"]["uuid"]
    response = await client.put(
        f"/v1/meal-plans/{uuid}",
        json=_replace_payload(created["data"], name="Semaine modifiée"),
        headers={"If-Match": created["etag"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Semaine modifiée"
    assert response.headers.get("etag") == 'W/"2"'


async def test_patch_set_headcount(client, created):
    uuid = created["data"]["uuid"]
    response = await client.patch(
        f"/v1/meal-plans/{uuid}",
        json={
            "operations": [
                {
                    "op": "set_headcount",
                    "slot_date": DEFAULT_DATE_START.isoformat(),
                    "slot_code": "lunch",
                    "headcount": 3,
                }
            ]
        },
        headers={"If-Match": created["etag"]},
    )
    assert response.status_code == 200
    slot = next(
        item
        for item in response.json()["data"]["slots"]
        if item["date"] == DEFAULT_DATE_START.isoformat() and item["slot_code"] == "lunch"
    )
    assert slot["headcount"] == 3


async def test_patch_not_found_returns_404(client):
    response = await client.patch(
        "/v1/meal-plans/01951234-5678-7abc-def0-000000000000",
        json={"operations": []},
        headers={"If-Match": 'W/"1"'},
    )
    assert response.status_code == 404


async def test_delete_hides_from_get(client, created):
    uuid = created["data"]["uuid"]
    response = await client.delete(f"/v1/meal-plans/{uuid}", headers={"If-Match": created["etag"]})
    assert response.status_code == 204
    assert (await client.get(f"/v1/meal-plans/{uuid}")).status_code == 404


async def test_list_empty(client):
    response = await client.get("/v1/meal-plans/")
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == []
    assert data["pagination"]["total"] == 0


async def test_list_returns_all(client):
    await client.post("/v1/meal-plans/", json=_payload(name="Semaine 1"))
    await client.post("/v1/meal-plans/", json=_payload(name="Semaine 2", date_start=DEFAULT_DATE_END, date_end=DEFAULT_DATE_END))
    response = await client.get("/v1/meal-plans/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert data["pagination"]["total"] == 2
    assert response.headers.get("x-total-count") == "2"


async def test_list_filtered_by_status(client, created):
    response = await client.get("/v1/meal-plans/", params={"status": "draft"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["status"] == "draft"


async def test_list_filter_no_match(client, created):
    response = await client.get("/v1/meal-plans/", params={"status": "done"})
    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_calendar_defaults_to_next_15_days(client):
    response = await client.get("/v1/meal-plans/calendar")
    assert response.status_code == 200
    data = response.json()["data"]
    today = date.today()

    assert data["name"] == "Planning perpétuel"
    assert data["date_start"] == today.isoformat()
    assert data["date_end"] == (today + timedelta(days=14)).isoformat()
    assert len(data["slots"]) == 30


async def test_calendar_range_can_be_six_months_ahead(client):
    start = date.today() + timedelta(days=180)
    end = start + timedelta(days=2)
    response = await client.get(
        "/v1/meal-plans/calendar",
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
    )
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["date_start"] == start.isoformat()
    assert data["date_end"] == end.isoformat()
    assert len(data["slots"]) == 6


async def test_calendar_uses_household_schedule_headcount(client):
    await _set_household_schedule(
        client,
        [
            {
                "week_parity": "even",
                "school_period_type": "regular",
                "day_of_week": "monday",
                "meal_slot_code": "lunch",
                "headcount": 4,
            }
        ],
    )

    response = await client.get(
        "/v1/meal-plans/calendar",
        params={"date_from": "2026-01-05", "date_to": "2026-01-05"},
    )

    assert response.status_code == 200
    lunch = next(slot for slot in response.json()["data"]["slots"] if slot["slot_code"] == "lunch")
    assert lunch["headcount"] == 4
    assert lunch["headcount_source"] == "household_schedule"


async def test_calendar_patch_adds_recipe_without_precreated_plan_period(client):
    target_date = date.today() + timedelta(days=180)
    recipe_uuid = str(uuid4())

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "dinner",
                    "item": {"item_type": "recipe", "recipe_uuid": recipe_uuid, "headcount": 1},
                }
            ]
        },
    )
    assert response.status_code == 200
    slot = next(item for item in response.json()["data"]["slots"] if item["slot_code"] == "dinner")

    assert slot["date"] == target_date.isoformat()
    assert slot["items"][0]["item_type"] == "recipe"
    assert slot["items"][0]["recipe_uuid"] == recipe_uuid


async def test_calendar_patch_adds_recipe_with_item_headcount(client):
    target_date = date.today() + timedelta(days=180)
    recipe_uuid = str(uuid4())

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "dinner",
                    "item": {"item_type": "recipe", "recipe_uuid": recipe_uuid, "headcount": 4},
                }
            ]
        },
    )
    assert response.status_code == 200
    slot = next(item for item in response.json()["data"]["slots"] if item["slot_code"] == "dinner")

    assert slot["items"][0]["headcount"] == 4


async def test_calendar_patch_can_create_global_custom_meal_slot(client):
    target_date = date.today() + timedelta(days=180)
    await _set_meal_slots(
        client,
        [
            {"code": "lunch", "label": "Déjeuner", "position": 0},
            {"code": "dinner", "label": "Dîner", "position": 1},
            {"code": "gouter", "label": "Goûter", "position": 2},
        ],
    )

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": (target_date + timedelta(days=1)).isoformat()},
        json={
            "operations": [
                {
                    "op": "set_headcount",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "gouter",
                    "headcount": 2,
                }
            ]
        },
    )
    assert response.status_code == 200

    day_slots = [item for item in response.json()["data"]["slots"] if item["date"] == target_date.isoformat()]
    next_day_slots = [
        item
        for item in response.json()["data"]["slots"]
        if item["date"] == (target_date + timedelta(days=1)).isoformat()
    ]
    assert [slot["slot_code"] for slot in day_slots] == ["lunch", "dinner", "gouter"]
    assert [slot["slot_code"] for slot in next_day_slots] == ["lunch", "dinner", "gouter"]
    assert day_slots[2]["headcount"] == 2


async def test_calendar_patch_rejects_undeclared_custom_meal_slot(client):
    target_date = date.today() + timedelta(days=180)

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "set_headcount",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "gouter",
                    "headcount": 2,
                }
            ]
        },
    )

    assert response.status_code == 422


async def test_calendar_patch_adds_ingredient_to_custom_meal_slot(client):
    target_date = date.today() + timedelta(days=180)
    ingredient_uuid = str(uuid4())
    await _set_meal_slots(
        client,
        [
            {"code": "lunch", "label": "Déjeuner", "position": 0},
            {"code": "dinner", "label": "Dîner", "position": 1},
            {"code": "petit-dejeuner", "label": "Petit-déjeuner", "position": 2},
        ],
    )

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "petit-dejeuner",
                    "item": {
                        "item_type": "ingredient",
                        "ingredient_uuid": ingredient_uuid,
                        "ingredient_name": "Pain",
                        "ingredient_quantity": 2,
                        "ingredient_unit": "tranche",
                        "headcount": 2,
                    },
                }
            ]
        },
    )
    assert response.status_code == 200

    slot = next(item for item in response.json()["data"]["slots"] if item["slot_code"] == "petit-dejeuner")
    assert slot["items"][0]["ingredient_name"] == f"Ingrédient {ingredient_uuid}"
    assert slot["items"][0]["ingredient_unit"] == "x"
    assert slot["items"][0]["headcount"] == 2

    projection_response = await client.get(f"/v1/meal-plans/{response.json()['data']['uuid']}/shopping-projection")
    assert projection_response.status_code == 200
    line = projection_response.json()["data"]["ingredients"][0]["lines"][0]
    assert line["slot_code"] == "petit-dejeuner"
    assert line["headcount"] == 2


async def test_patch_can_create_custom_meal_slot_on_existing_plan(client, created):
    uuid = created["data"]["uuid"]
    await _set_meal_slots(
        client,
        [
            {"code": "lunch", "label": "Déjeuner", "position": 0},
            {"code": "dinner", "label": "Dîner", "position": 1},
            {"code": "gouter", "label": "Goûter", "position": 2},
        ],
    )
    response = await client.patch(
        f"/v1/meal-plans/{uuid}",
        json={
            "operations": [
                {
                    "op": "set_headcount",
                    "slot_date": DEFAULT_DATE_START.isoformat(),
                    "slot_code": "gouter",
                    "headcount": 4,
                }
            ]
        },
        headers={"If-Match": created["etag"]},
    )
    assert response.status_code == 200

    day_slots = [item for item in response.json()["data"]["slots"] if item["date"] == DEFAULT_DATE_START.isoformat()]
    assert [slot["slot_code"] for slot in day_slots] == ["lunch", "dinner", "gouter"]
    assert day_slots[2]["headcount"] == 4


async def test_shopping_projection_scales_manual_ingredient_by_item_headcount(client):
    target_date = date.today() + timedelta(days=180)
    ingredient_uuid = str(uuid4())

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "lunch",
                    "item": {
                        "item_type": "ingredient",
                        "ingredient_uuid": ingredient_uuid,
                        "ingredient_name": "Yaourt",
                        "ingredient_quantity": 1,
                        "ingredient_unit": "pot",
                        "headcount": 3,
                    },
                }
            ]
        },
    )
    assert response.status_code == 200

    projection_response = await client.get(f"/v1/meal-plans/{response.json()['data']['uuid']}/shopping-projection")
    assert projection_response.status_code == 200
    ingredient = projection_response.json()["data"]["ingredients"][0]

    assert ingredient["aggregated"]["quantity"] == 3
    assert ingredient["lines"][0]["headcount"] == 3


async def test_calendar_shopping_projection_scales_recipe_ingredients_by_planned_headcount(client):
    target_date = date.today() + timedelta(days=181)
    recipe_uuid = str(uuid4())
    ingredient_uuid = str(uuid4())

    response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "lunch",
                    "item": {
                        "item_type": "recipe",
                        "recipe_uuid": recipe_uuid,
                        "headcount": 6,
                        "recipe_snapshot": {
                            "recipe_uuid": recipe_uuid,
                            "title": "Sauce tomate",
                            "servings_default": 3,
                            "total_duration_min": 20,
                            "ingredients": [
                                {
                                    "ingredient_uuid": ingredient_uuid,
                                    "name": "Tomates",
                                    "quantity": 100,
                                    "unit": "g",
                                }
                            ],
                            "snapshot_taken_at": datetime.now(timezone.utc).isoformat(),
                            "recipe_version": 1,
                        },
                    },
                }
            ]
        },
    )
    assert response.status_code == 200

    projection_response = await client.get(
        "/v1/meal-plans/calendar/shopping-projection",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
    )
    assert projection_response.status_code == 200
    ingredient = projection_response.json()["data"]["ingredients"][0]
    line = ingredient["lines"][0]

    assert ingredient["aggregated"]["quantity"] == 200
    assert line["headcount"] == 6
    assert line["scale_factor"] == 2


async def test_calendar_patch_can_replace_recipe_on_same_day(client):
    target_date = date.today() + timedelta(days=181)
    first_recipe_uuid = str(uuid4())
    second_recipe_uuid = str(uuid4())

    create_response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "lunch",
                    "item": {"item_type": "recipe", "recipe_uuid": first_recipe_uuid, "headcount": 1},
                }
            ]
        },
    )
    created_slot = next(item for item in create_response.json()["data"]["slots"] if item["slot_code"] == "lunch")
    item_uuid = created_slot["items"][0]["uuid"]

    replace_response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": target_date.isoformat(), "date_to": target_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "update_item",
                    "slot_date": target_date.isoformat(),
                    "slot_code": "lunch",
                    "item_uuid": item_uuid,
                    "item": {"item_type": "recipe", "recipe_uuid": second_recipe_uuid, "headcount": 1},
                }
            ]
        },
        headers={"If-Match": create_response.headers["etag"]},
    )
    slot = next(item for item in replace_response.json()["data"]["slots"] if item["slot_code"] == "lunch")

    assert replace_response.status_code == 200
    assert len(slot["items"]) == 1
    assert slot["items"][0]["recipe_uuid"] == second_recipe_uuid


async def test_calendar_patch_accepts_stale_if_match_for_independent_slots(client):
    first_date = date.today() + timedelta(days=182)
    second_date = first_date + timedelta(days=1)
    first_recipe_uuid = str(uuid4())
    second_recipe_uuid = str(uuid4())

    calendar_response = await client.get(
        "/v1/meal-plans/calendar",
        params={"date_from": first_date.isoformat(), "date_to": second_date.isoformat()},
    )
    stale_etag = calendar_response.headers["etag"]

    first_patch_response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": first_date.isoformat(), "date_to": second_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": first_date.isoformat(),
                    "slot_code": "lunch",
                    "item": {"item_type": "recipe", "recipe_uuid": first_recipe_uuid, "headcount": 1},
                }
            ]
        },
        headers={"If-Match": stale_etag},
    )
    assert first_patch_response.status_code == 200

    second_patch_response = await client.patch(
        "/v1/meal-plans/calendar",
        params={"date_from": first_date.isoformat(), "date_to": second_date.isoformat()},
        json={
            "operations": [
                {
                    "op": "add_item",
                    "slot_date": second_date.isoformat(),
                    "slot_code": "dinner",
                    "item": {"item_type": "recipe", "recipe_uuid": second_recipe_uuid, "headcount": 1},
                }
            ]
        },
        headers={"If-Match": stale_etag},
    )
    assert second_patch_response.status_code == 200

    slots = second_patch_response.json()["data"]["slots"]
    first_slot = next(item for item in slots if item["date"] == first_date.isoformat() and item["slot_code"] == "lunch")
    second_slot = next(item for item in slots if item["date"] == second_date.isoformat() and item["slot_code"] == "dinner")
    assert first_slot["items"][0]["recipe_uuid"] == first_recipe_uuid
    assert second_slot["items"][0]["recipe_uuid"] == second_recipe_uuid


async def test_transition_to_confirmed(client, created):
    uuid = created["data"]["uuid"]
    response = await client.post(
        f"/v1/meal-plans/{uuid}/transitions",
        json={"target_status": "confirmed"},
        headers={"If-Match": created["etag"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "confirmed"


async def test_shopping_projection(client, created):
    uuid = created["data"]["uuid"]
    response = await client.get(f"/v1/meal-plans/{uuid}/shopping-projection")
    assert response.status_code == 200
    assert response.json()["data"]["meal_plan_uuid"] == uuid


async def test_purge_returns_200(client):
    response = await client.delete("/admin/purge")
    assert response.status_code == 200


async def test_purge_count_is_zero_when_nothing_eligible(client):
    await client.post("/v1/meal-plans/", json=_payload())
    response = await client.delete("/admin/purge")
    assert response.json()["total"] == 0
