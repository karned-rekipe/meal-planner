"""OAuth resource-server policy for the Meal Planner MCP transport."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastmcp.server.auth import AccessToken, JWTVerifier, RemoteAuthProvider
from pydantic import AnyHttpUrl

from arclith.infrastructure.config import load_config_dir

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_CLOCK_SKEW_SECONDS = 30


def _is_auth_disabled() -> bool:
    return os.getenv("REKIPE_AUTH_DISABLED", "").strip().lower() in _TRUE_VALUES


class KeycloakJWTVerifier(JWTVerifier):
    """Verify Keycloak signatures, temporal claims, subject and realm role."""

    def __init__(self, *, required_role: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.required_role = required_role

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = await super().load_access_token(token)
        if access_token is None:
            return None

        claims = access_token.claims
        now = int(time.time())
        if not _valid_expiration_numeric_date(claims.get("exp"), now):
            return None
        if not _valid_future_numeric_date(claims.get("nbf"), now + _CLOCK_SKEW_SECONDS):
            return None
        if not _valid_future_numeric_date(claims.get("iat"), now + _CLOCK_SKEW_SECONDS):
            return None
        if not _valid_subject(claims.get("sub")):
            return None
        if not _has_required_realm_role(claims, self.required_role):
            return None

        return access_token


def _valid_future_numeric_date(value: Any, latest: int) -> bool:
    if value is None:
        return True
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value <= latest


def _valid_expiration_numeric_date(value: Any, now: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value > now


def _valid_subject(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_required_realm_role(claims: dict[str, Any], required_role: str | None) -> bool:
    if required_role is None:
        return True
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return isinstance(roles, list) and required_role in roles


def build_mcp_auth_provider() -> RemoteAuthProvider | None:
    """Build the OAuth provider used by the public HTTP MCP transport."""

    if _is_auth_disabled():
        return None

    config = load_config_dir(_CONFIG_PATH)
    keycloak = config.keycloak
    if keycloak is None:
        raise RuntimeError("config.keycloak requis pour protéger le transport MCP")

    public_base_url = os.getenv(
        "REKIPE_MCP_PUBLIC_BASE_URL",
        "http://127.0.0.1:8011",
    ).rstrip("/")
    issuer_url = os.getenv(
        "REKIPE_MCP_AUTH_ISSUER_URL",
        f"{keycloak.url.rstrip('/')}/realms/{keycloak.realm}",
    ).rstrip("/")
    jwks_uri = os.getenv(
        "REKIPE_MCP_AUTH_JWKS_URI",
        f"{keycloak.url.rstrip('/')}/realms/{keycloak.realm}/protocol/openid-connect/certs",
    )
    required_role = os.getenv("REKIPE_MCP_AUTH_REQUIRED_ROLE", "rekipe:mcp-access").strip()
    if not required_role:
        raise RuntimeError("REKIPE_MCP_AUTH_REQUIRED_ROLE ne peut pas être vide")

    verifier = KeycloakJWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer_url,
        algorithm="RS256",
        required_role=required_role,
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(issuer_url)],
        base_url=public_base_url,
        resource_name="Rekipe Meal Planner MCP",
    )
