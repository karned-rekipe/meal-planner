from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from adapters.input.fastapi.dependencies import inject_tenant_uri, require_auth
from adapters.input.fastapi.routers import HouseholdMemberRouter
from adapters.output.memory.repository import InMemoryHouseholdMemberRepository
from application.services.meal_plan_service import MealPlanService


def _etag(response) -> str:
    value = response.headers.get("etag")
    assert value
    return value


async def _create_member(client: AsyncClient, name: str = "Alice") -> tuple[dict, str]:
    response = await client.post(
        "/v1/household-members/",
        json={"name": name, "member_type": "resident", "gender": "female", "birth_year": 2018, "color": "#4a90d9"},
    )
    assert response.status_code == 201
    return response.json()["data"], _etag(response)


async def test_household_member_router_crud(repo, logger):
    service = MealPlanService(repo, logger, household_member_repository=InMemoryHouseholdMemberRepository())
    app = FastAPI()
    app.include_router(HouseholdMemberRouter(service, logger).router)
    app.dependency_overrides[inject_tenant_uri] = lambda: None
    app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created, etag = await _create_member(client)
        assert created["name"] == "Alice"
        assert created["avatar_data"] is None

        list_response = await client.get("/v1/household-members/")
        assert list_response.status_code == 200
        assert [item["name"] for item in list_response.json()["data"]] == ["Alice"]

        update_response = await client.put(
            f"/v1/household-members/{created['uuid']}",
            json={
                "name": "Alice B.",
                "member_type": "resident",
                "gender": "female",
                "birth_year": 2018,
                "color": "#2f855a",
            },
            headers={"If-Match": etag},
        )
        assert update_response.status_code == 200
        assert update_response.json()["data"]["name"] == "Alice B."
        assert update_response.json()["data"]["version"] == 2
        etag = _etag(update_response)

        avatar_response = await client.put(
            f"/v1/household-members/{created['uuid']}/avatar",
            json={"avatar_data": "data:image/png;base64,AAAA"},
            headers={"If-Match": etag},
        )
        assert avatar_response.status_code == 200
        assert avatar_response.json()["data"]["avatar_data"] == "data:image/png;base64,AAAA"
        etag = _etag(avatar_response)

        delete_response = await client.delete(
            f"/v1/household-members/{created['uuid']}",
            headers={"If-Match": etag},
        )
        assert delete_response.status_code == 204

        list_response = await client.get("/v1/household-members/")
        assert list_response.json()["data"] == []


async def test_household_member_router_returns_404_and_412(repo, logger):
    service = MealPlanService(repo, logger, household_member_repository=InMemoryHouseholdMemberRepository())
    app = FastAPI()
    app.include_router(HouseholdMemberRouter(service, logger).router)
    app.dependency_overrides[inject_tenant_uri] = lambda: None
    app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created, etag = await _create_member(client)
        conflict_response = await client.put(
            f"/v1/household-members/{created['uuid']}",
            json={"name": "Alice", "member_type": "resident", "gender": None, "birth_year": None, "color": "#4a90d9"},
            headers={"If-Match": 'W/"99"'},
        )
        assert conflict_response.status_code == 412

        delete_response = await client.delete(f"/v1/household-members/{created['uuid']}", headers={"If-Match": etag})
        assert delete_response.status_code == 204

        missing_response = await client.delete(f"/v1/household-members/{created['uuid']}", headers={"If-Match": etag})
        assert missing_response.status_code == 404
