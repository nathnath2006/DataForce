"""TamTam's real OAuth metadata (fetched 2026-10-17) served by respx; nothing reaches the network.

`respx.mock(assert_all_mocked=True)` makes any request without a registered route an error, so a
test that would touch the real TamTam fails instead.
"""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qs

import httpx
import respx

ISSUER = "https://api.tamtam.ai"
MCP_URL = "https://api.tamtam.ai/mcp"
PRM = {"resource": MCP_URL, "authorization_servers": [ISSUER]}
AS_META = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "registration_endpoint": f"{ISSUER}/register",
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "response_types_supported": ["code"],
    "code_challenge_methods_supported": ["S256"],
    "token_endpoint_auth_methods_supported": ["none"],
}
PRM_URL = f"{ISSUER}/.well-known/oauth-protected-resource/mcp"
PRM_ROOT_URL = f"{ISSUER}/.well-known/oauth-protected-resource"
AS_URL = f"{ISSUER}/.well-known/oauth-authorization-server"
WWW_AUTHENTICATE = 'Bearer resource_metadata="/.well-known/oauth-protected-resource/mcp"'

CLIENT_ID = "client-abc"
ACCESS_1, REFRESH_1 = "access-token-ONE", "refresh-token-ONE"
ACCESS_2, REFRESH_2 = "access-token-TWO", "refresh-token-TWO"
CODE = "auth-code-xyz"
SECRETS = (ACCESS_1, REFRESH_1, ACCESS_2, REFRESH_2, CODE)


class TamTamStub:
    """Registers the four TamTam endpoints on a respx router and records what was sent."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.mock = mock
        self.prm = copy.deepcopy(PRM)
        self.as_meta = copy.deepcopy(AS_META)
        self.register_calls: list[dict[str, Any]] = []
        self.token_calls: list[dict[str, str]] = []
        self.revoke_calls: list[dict[str, str]] = []
        self.code_reply: tuple[int, Any] | None = None  # override for the code exchange
        self.refresh_reply: tuple[int, Any] | None = None  # override for the refresh
        self.registered_client_id = CLIENT_ID
        mock.get(PRM_URL).mock(side_effect=lambda r: httpx.Response(200, json=self.prm))
        mock.get(AS_URL).mock(side_effect=lambda r: httpx.Response(200, json=self.as_meta))
        mock.post(f"{ISSUER}/register").mock(side_effect=self._register)
        mock.post(f"{ISSUER}/token").mock(side_effect=self._token)
        mock.post(f"{ISSUER}/revoke").mock(side_effect=self._revoke)

    @property
    def traffic(self) -> int:
        return len(self.mock.calls)

    def _register(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        self.register_calls.append(body)
        return httpx.Response(
            201,
            json={"client_id": self.registered_client_id, "redirect_uris": body["redirect_uris"]},
        )

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_calls.append(form)
        override = (
            self.code_reply if form["grant_type"] == "authorization_code" else self.refresh_reply
        )
        if override is not None:
            return httpx.Response(override[0], json=override[1])
        if form["grant_type"] == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS_1,
                    "refresh_token": REFRESH_1,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_2,
                "refresh_token": REFRESH_2,
                "token_type": "bearer",
                "expires_in": 3600,
            },
        )

    def _revoke(self, request: httpx.Request) -> httpx.Response:
        self.revoke_calls.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={})
