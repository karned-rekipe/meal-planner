from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import fastmcp
import pytest
from authlib.jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth import RemoteAuthProvider
from httpx import ASGITransport, AsyncClient

from adapters.input.fastmcp.authorization import KeycloakJWTVerifier, build_mcp_auth_provider

ISSUER = "https://keycloak.example.test/realms/rekipe"
BASE_URL = "https://rekipe.example.test/api/meal-planner-mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/api/meal-planner-mcp/mcp"


@pytest.fixture(scope="module")
def signing_keys() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _token(private_key: bytes, *, drop_claims: tuple[str, ...] = (), **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "agent-123",
        "azp": "rekipe-mcp-codex",
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "realm_access": {"roles": ["rekipe:mcp-access"]},
    }
    claims.update(overrides)
    for claim in drop_claims:
        claims.pop(claim, None)
    return jwt.encode({"alg": "RS256"}, claims, private_key).decode()


def _verifier(public_key: bytes) -> KeycloakJWTVerifier:
    return KeycloakJWTVerifier(
        public_key=public_key.decode(),
        issuer=ISSUER,
        algorithm="RS256",
        required_role="rekipe:mcp-access",
    )


async def test_keycloak_verifier_accepts_authorized_realm_token(signing_keys) -> None:
    private_key, public_key = signing_keys

    access_token = await _verifier(public_key).verify_token(_token(private_key))

    assert access_token is not None
    assert access_token.client_id == "rekipe-mcp-codex"
    assert access_token.claims["sub"] == "agent-123"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://another-issuer.example.test"},
        {"realm_access": {"roles": []}},
        {"nbf": int(time.time()) + 3600},
        {"iat": int(time.time()) + 3600},
        {"exp": int(time.time()) - 60},
        {"exp": None},
        {"sub": ""},
    ],
)
async def test_keycloak_verifier_rejects_invalid_token(signing_keys, overrides) -> None:
    private_key, public_key = signing_keys

    assert await _verifier(public_key).verify_token(_token(private_key, **overrides)) is None


async def test_keycloak_verifier_rejects_missing_expiration(signing_keys) -> None:
    private_key, public_key = signing_keys

    assert await _verifier(public_key).verify_token(
        _token(private_key, drop_claims=("exp",)),
    ) is None


def test_build_auth_provider_uses_public_resource_and_internal_jwks(monkeypatch) -> None:
    config = MagicMock()
    config.keycloak.url = "http://keycloak.keycloak.svc.cluster.local"
    config.keycloak.realm = "rekipe"
    monkeypatch.delenv("REKIPE_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("REKIPE_MCP_PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setenv("REKIPE_MCP_AUTH_ISSUER_URL", ISSUER)
    monkeypatch.setenv("REKIPE_MCP_AUTH_REQUIRED_ROLE", "rekipe:mcp-access")

    with patch("adapters.input.fastmcp.authorization.load_config_dir", return_value=config):
        provider = build_mcp_auth_provider()

    assert isinstance(provider, RemoteAuthProvider)
    assert str(provider.base_url) == BASE_URL
    assert provider.token_verifier.issuer == ISSUER
    assert provider.token_verifier.jwks_uri == (
        "http://keycloak.keycloak.svc.cluster.local/realms/rekipe/protocol/openid-connect/certs"
    )
    assert provider.token_verifier.required_role == "rekipe:mcp-access"


def test_build_auth_provider_can_only_be_disabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("REKIPE_AUTH_DISABLED", "true")

    assert build_mcp_auth_provider() is None


def test_build_auth_provider_rejects_blank_required_role(monkeypatch) -> None:
    config = MagicMock()
    config.keycloak.url = "http://keycloak.keycloak.svc.cluster.local"
    config.keycloak.realm = "rekipe"
    monkeypatch.delenv("REKIPE_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("REKIPE_MCP_AUTH_REQUIRED_ROLE", "   ")

    with (
        patch("adapters.input.fastmcp.authorization.load_config_dir", return_value=config),
        pytest.raises(RuntimeError, match="ne peut pas être vide"),
    ):
        build_mcp_auth_provider()


@pytest.fixture
def protected_mcp_app(monkeypatch):
    config = MagicMock()
    config.keycloak.url = "https://keycloak.example.test"
    config.keycloak.realm = "rekipe"
    monkeypatch.delenv("REKIPE_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("REKIPE_MCP_PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setenv("REKIPE_MCP_AUTH_ISSUER_URL", ISSUER)

    with patch("adapters.input.fastmcp.authorization.load_config_dir", return_value=config):
        provider = build_mcp_auth_provider()
    mcp = fastmcp.FastMCP("protected-meal-planner", auth=provider)
    return mcp.http_app(path="/mcp", stateless_http=True, json_response=True)


async def test_protected_resource_metadata_is_public(protected_mcp_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=protected_mcp_app),
        base_url="https://rekipe.example.test",
    ) as client:
        response = await client.get(METADATA_PATH)

    assert response.status_code == 200
    assert response.json()["resource"] == f"{BASE_URL}/mcp"
    assert response.json()["authorization_servers"] == [ISSUER]
    assert response.json()["resource_name"] == "Rekipe Meal Planner MCP"


async def test_mcp_transport_rejects_anonymous_request(protected_mcp_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=protected_mcp_app),
        base_url="https://rekipe.example.test",
    ) as client:
        response = await client.post("/mcp", json={})

    assert response.status_code == 401
    assert f'resource_metadata="https://rekipe.example.test{METADATA_PATH}"' in (
        response.headers["www-authenticate"]
    )
