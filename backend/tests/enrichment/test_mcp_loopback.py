"""The real `mcp` SDK transport against an in-process MCP server on 127.0.0.1.

No external network. Proves the parts mocks cannot: the bearer header really goes out on the
streamable-HTTP connection, `initialize` / `list_tools` / `call_tool` work with the installed SDK,
and an auth rejection surfaces as an actionable EnrichmentError.
"""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

from app.domain.schemas import EnrichmentRequest
from app.enrichment.errors import EnrichmentError
from app.enrichment.tamtam_mcp import TamTamMCPEnrichment
from tests.enrichment.helpers import make_settings

uvicorn = pytest.importorskip("uvicorn")
mcpserver = pytest.importorskip("mcp.server.mcpserver")  # mcp >= 2: MCPServer

TOKEN = "loopback-token-123"
EMAIL = "jane.doe@acme.example"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BearerGate:
    """ASGI wrapper: records the Authorization header, answers 401 without the right token."""

    def __init__(self, app, expected: str) -> None:
        self.app, self.expected, self.seen = app, f"Bearer {expected}", []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"").decode()
            self.seen.append(auth)
            if auth != self.expected:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


@pytest.fixture
async def mcp_url():
    server = mcpserver.MCPServer("fake-tamtam")

    @server.tool()
    def enrich_contact(full_name: str, company_name: str, want: list[str]) -> str:
        """Find a contact's email or mobile (test double)."""
        return json.dumps({"email": EMAIL, "credits_used": 1, "echo_want": want})

    gate = BearerGate(server.streamable_http_app(), TOKEN)
    port = _free_port()
    config = uvicorn.Config(gate, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    for _ in range(200):
        if srv.started:
            break
        await asyncio.sleep(0.05)
    assert srv.started
    try:
        yield f"http://127.0.0.1:{port}/mcp", gate
    finally:
        srv.should_exit = True
        await task


REQUEST = EnrichmentRequest(full_name="Jane Doe", company_name="Acme", want=["email"])


async def test_real_transport_sends_the_bearer_token_and_calls_the_tool(mcp_url):
    url, gate = mcp_url
    provider = TamTamMCPEnrichment(
        make_settings(tamtam_mcp_url=url, tamtam_mcp_token=TOKEN), timeout_s=30
    )
    result = await provider.enrich_contact(REQUEST, allow_paid=True)

    assert result.email == EMAIL and result.credits_used == 1.0
    assert result.raw_tool == "enrich_contact" and result.provider == "tamtam_mcp"
    assert gate.seen and set(gate.seen) == {f"Bearer {TOKEN}"}  # on every request


async def test_a_rejected_token_gives_an_actionable_error_without_the_token(mcp_url):
    url, _ = mcp_url
    provider = TamTamMCPEnrichment(
        make_settings(tamtam_mcp_url=url, tamtam_mcp_token="wrong"), timeout_s=30
    )
    with pytest.raises(EnrichmentError) as exc:
        await provider.enrich_contact(REQUEST, allow_paid=True)
    assert "TAMTAM_MCP_TOKEN" in str(exc.value) and "wrong" not in str(exc.value)
