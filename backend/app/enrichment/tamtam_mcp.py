"""TamTam MCP contact enrichment (email / mobile) over a remote MCP server.

WHAT IS KNOWN (public information about TamTam, not verified by us against a live account):
  * The MCP server is a remote HTTP server at https://api.tamtam.ai/mcp (streamable-HTTP
    transport).
  * Users connect it to their AI assistant and sign in with OAuth. A TamTam account is required
    and the free credits are limited. Lookups spend credits.

WHAT IS ASSUMED (every item below is "assumed from the public site, unverified"; each one is
configurable or isolated in one function so it is cheap to fix once we have a real account):
  * Bearer token. OAuth is an interactive authorization-code flow, which a batch backend cannot
    run. We therefore take an already-issued access token from `TAMTAM_MCP_TOKEN` (settings
    `tamtam_mcp_token`, a SecretStr) and send it as `Authorization: Bearer <token>`. To get one:
    sign in once with any MCP client that supports OAuth (e.g. `npx mcp-remote
    https://api.tamtam.ai/mcp`, or the MCP Inspector), copy the access token it stores, and put
    it in backend/.env (chmod 600). Tokens expire and we do not refresh them in M1; the mcp SDK's
    `mcp.client.auth.OAuthClientProvider` is the way to do the full flow later, or ask TamTam
    for a long-lived API key. The URL must be https (http only for a loopback stub in dev/test),
    checked when the client is built, so the token can never go out in cleartext.
  * Tool names are not public. We call `list_tools()` and call ONLY a tool whose name is in the
    allow-list `tool_map` (default candidates `enrich_contact`, `find_contact`, `enrich_person`,
    ...). There is no keyword fallback (SR2-03): a server can publish `send_email_to_contact`
    or `enrich_and_push_to_crm` with a convincing description, and a paid, person-data call must
    never land on a tool we did not name. When nothing matches, the error lists the server's
    tools and SUGGESTS candidates; the human pins one in `tool_map`. If the server publishes MCP
    tool annotations, a tool not marked `readOnlyHint=true` (or marked `destructiveHint=true`) is
    refused too, unless its name is passed in `reviewed_tools`.
  * Tool arguments are mapped onto the tool's advertised `inputSchema` (full name, company,
    domain, requested fields); tool results are parsed defensively (JSON text or structured
    content; unknown shapes yield "nothing found", not a crash) after a hard size / depth cap.
  * Costs: an email lookup is assumed to cost 1 credit and a mobile lookup 10 credits
    (`credit_costs`). The guard has three layers (SR2-04): (1) before any network traffic, a
    lookup with a positive estimate needs `allow_paid is True` (strictly) and must not exceed
    `settings.enrichment_max_credits_per_call`; (2) once the tool is chosen, its cost
    (`tool_costs`, unknown => the ceiling, i.e. treated as paid at the ceiling) must not exceed
    the ceiling either; (3) the credit figure the server reports is validated (finite, >= 0, <=
    the ceiling) and the result is flagged `anomalous` otherwise. Only keys that mean "spent"
    count (`credits_used`...); a bare `credits` / `balance` is ignored (it is usually a balance).

Contact values (emails, phone numbers) are never logged and never put in exception messages.
Server-controlled text that does reach a message is stripped of control / ANSI characters, capped,
and masked of contact values, the token and the person / company being looked up (SR2-11).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings
from app.domain.schemas import EnrichmentRequest, EnrichmentResult
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError, PaidLookupRefused

log = logging.getLogger(__name__)

PROVIDER_NAME = "tamtam_mcp"

# Assumed, unverified: candidate tool names per requested field, in priority order. This is the
# allow-list: nothing else is ever called.
DEFAULT_TOOL_MAP: dict[str, tuple[str, ...]] = {
    "email": ("enrich_contact", "find_contact", "enrich_person", "find_email"),
    "mobile": ("enrich_contact", "find_contact", "enrich_person", "find_phone", "find_mobile"),
}
# Assumed, unverified: credits per field (public site: ~1 per email, ~10 per mobile).
DEFAULT_CREDIT_COSTS: dict[str, float] = {"email": 1.0, "mobile": 10.0}

# Words used ONLY to suggest names in an error message, never to choose a tool to call.
_SUGGEST_WORDS = ("enrich", "find", "lookup", "look_up", "reveal", "contact", "person", "email",
                  "phone", "mobile")  # fmt: skip

# Hard limits on what a server can make us parse or print (SR2-10 / SR2-11).
MAX_RESULT_CHARS = 64_000
MAX_JSON_DEPTH = 8
MAX_WALK_NODES = 5_000
MAX_LEAF_CHARS = 2_048
MAX_TOOLS = 200
MAX_NAME_CHARS = 64
MAX_SUGGESTED_NAMES = 20
MAX_ERROR_CHARS = 160
MAX_DESCRIPTION_CHARS = 500

# Every pattern is bounded: scanning a long string is linear, so a hostile result cannot stall
# the event loop (the old `[...]+@` was quadratic: 80 KB took 4 s, and asyncio.timeout cannot
# interrupt synchronous code).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){1,5}")
_PHONE_RE = re.compile(r"\+?\d[\d .\-()]{6,24}\d")
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    # None = the server did not send annotations (nothing to check); else the two hints we use.
    annotations: dict[str, Any] | None = None


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """First present attribute: the `mcp` SDK is snake_case in 2.x and camelCase in 1.x."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _annotations(tool: Any) -> dict[str, Any] | None:
    raw = _attr(tool, "annotations", default=None)
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return {
            "readOnlyHint": raw.get("readOnlyHint", raw.get("read_only_hint")),
            "destructiveHint": raw.get("destructiveHint", raw.get("destructive_hint")),
        }
    return {
        "readOnlyHint": _attr(raw, "readOnlyHint", "read_only_hint", default=None),
        "destructiveHint": _attr(raw, "destructiveHint", "destructive_hint", default=None),
    }


def _tool_info(tool: Any) -> ToolInfo:
    schema = _attr(tool, "input_schema", "inputSchema", default=None)
    return ToolInfo(
        name=str(tool.name)[:200],
        description=str(_attr(tool, "description", default="") or "")[:MAX_DESCRIPTION_CHARS],
        input_schema=schema if isinstance(schema, dict) else {},
        annotations=_annotations(tool),
    )


# --- text we may surface -------------------------------------------------------------------------


MAX_CREDIT_CEILING = 1000.0
MAX_SOURCE_CHARS = 80


def _valid_cost(cost: Any) -> bool:
    return (
        isinstance(cost, int | float)
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and cost >= 0
    )


def check_ceiling(value: Any) -> float:
    """The per-call ceiling; EnrichmentConfigError unless finite, > 0 and <= 1000 (SR5-02)."""
    ok = isinstance(value, int | float) and not isinstance(value, bool)
    if not ok or not math.isfinite(value) or not 0 < value <= MAX_CREDIT_CEILING:
        raise EnrichmentConfigError(
            f"enrichment_max_credits_per_call must be finite, > 0 and <= {MAX_CREDIT_CEILING:g}"
        )
    return float(value)


def _strip_control(text: str) -> str:
    """No ANSI escape sequences, no control / format characters (newlines become spaces)."""
    text = _ANSI_RE.sub("", text)
    return "".join(
        " " if ch in "\r\n\t" else ch
        for ch in text
        if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co"} or ch in "\r\n\t"
    )


def _mask(text: str) -> str:
    """Remove anything that looks like a contact value from text we might surface. Looks at the
    first 1 KB only: callers cap what they print anyway."""
    return _PHONE_RE.sub("***", _EMAIL_RE.sub("***", text[:1024]))


def _names_to_mask(request: EnrichmentRequest, token: str | None) -> list[str]:
    values = [request.full_name, request.company_name, request.company_domain or ""]
    values += [part for part in request.full_name.split() if len(part) >= 2]
    if token:
        values.append(token)
    return sorted({v for v in values if len(v.strip()) >= 2}, key=len, reverse=True)


def safe_server_text(text: str, mask: Iterable[str] = ()) -> str:
    """Server-controlled text made printable in an error: control / ANSI stripped, contact values
    and every string in `mask` (the token, the person, the company) replaced by `***`, capped."""
    cleaned = _mask(_strip_control(text[:4096]))
    for needle in mask:
        cleaned = re.sub(re.escape(needle), "***", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()[:MAX_ERROR_CHARS]


def _safe_name(name: str) -> str:
    """A server-provided tool name made safe to print: word characters, dots and dashes only."""
    return re.sub(r"[^\w.\-]", "?", name)[:MAX_NAME_CHARS]


def _leaves(exc: BaseException) -> Iterable[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _leaves(sub)
    else:
        yield exc


def _describe_failure(exc: BaseException) -> str:
    """Class names and HTTP status only (never `str(exc)`: it may echo URLs or payloads)."""
    names: list[str] = []
    for leaf in _leaves(exc):
        names.append(type(leaf).__name__)
        status = getattr(getattr(leaf, "response", None), "status_code", None)
        if status in (401, 403):
            return _auth_message(status).removeprefix("TamTam MCP ")
    return ", ".join(dict.fromkeys(names))


def _auth_message(status: int) -> str:
    return (
        f"TamTam MCP authentication rejected (HTTP {status}); TAMTAM_MCP_TOKEN is missing, "
        "expired or not accepted by the server"
    )


# --- destination of the token --------------------------------------------------------------------

_DEV_ENVIRONMENTS = frozenset({"dev", "test"})


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_mcp_url(url: str, environment: str) -> None:
    """The bearer token goes to this URL: https only (http only for a loopback stub in dev /
    test), no credentials in the URL. Raises EnrichmentConfigError without echoing the value."""
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    if parts.username or parts.password:
        raise EnrichmentConfigError("TAMTAM_MCP_URL must not contain credentials")
    if parts.scheme == "https" and host:
        return
    if parts.scheme == "http" and host and _is_loopback(host) and environment in _DEV_ENVIRONMENTS:
        return
    raise EnrichmentConfigError(
        "TAMTAM_MCP_URL must be an https:// URL (http:// is only accepted for localhost in "
        "dev/test): the bearer token must never travel in cleartext"
    )


@asynccontextmanager
async def open_http_session(url: str, token: str):
    """Open an initialized MCP `ClientSession` over streamable HTTP with a bearer token.

    Verified against mcp 2.3.0 (`streamable_http_client` + an `httpx2` client carrying the auth
    header; see tests/enrichment/test_mcp_loopback.py). mcp 1.x releases that only have
    `streamablehttp_client(url, headers=...)` are handled by the fallback branch (written from the
    1.x API, not exercised here).

    mcp 2.x reports an HTTP 401 as a generic `MCPError`, so the HTTP status is recorded with a
    response hook and turned into an actionable `EnrichmentError` here.
    """
    from mcp import ClientSession

    headers = {"Authorization": f"Bearer {token}"}
    statuses: list[int] = []

    async def record_status(response: Any) -> None:
        if response.status_code >= 400:
            statuses.append(response.status_code)

    try:
        try:
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared._httpx_utils import create_mcp_http_client
        except ImportError:  # older mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(url, headers=headers) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session
            return

        async with create_mcp_http_client(headers=headers) as http_client:
            http_client.event_hooks["response"].append(record_status)
            async with streamable_http_client(url, http_client=http_client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session
    except Exception as exc:  # incl. ExceptionGroup from anyio task groups
        if isinstance(exc, EnrichmentError):
            raise
        if any(st in (401, 403) for st in statuses):
            raise EnrichmentError(_auth_message(statuses[-1])) from exc
        if statuses:
            raise EnrichmentError(f"TamTam MCP server answered HTTP {statuses[-1]}") from exc
        raise


@dataclass
class _CallState:
    """Whether a request that can be billed has left the building (for the timeout message)."""

    sent: bool = False


class TamTamMCPEnrichment:
    """`EnrichmentProvider` backed by the TamTam MCP server."""

    name = PROVIDER_NAME

    def __init__(
        self,
        settings: Settings,
        tool_map: Mapping[str, str | Sequence[str]] | None = None,
        credit_costs: Mapping[str, float] | None = None,
        *,
        tool_costs: Mapping[str, float] | None = None,
        reviewed_tools: Collection[str] = (),
        session_factory: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
        timeout_s: float = 60.0,
        token: str | None = None,
    ) -> None:
        check_mcp_url(settings.tamtam_mcp_url, settings.environment)
        self._settings = settings
        # An OAuth access token handed in by app.connectors takes precedence over
        # settings.tamtam_mcp_token. Every other guard is unchanged.
        self._token = token
        self._timeout_s = timeout_s
        self._session_factory = session_factory or self._default_session
        self._tool_map: dict[str, tuple[str, ...]] = dict(DEFAULT_TOOL_MAP)
        for field_name, names in (tool_map or {}).items():
            self._tool_map[field_name] = (names,) if isinstance(names, str) else tuple(names)
        self._costs: dict[str, float] = {**DEFAULT_CREDIT_COSTS, **(credit_costs or {})}
        for name, cost in self._costs.items():
            if not _valid_cost(cost):
                raise EnrichmentConfigError(f"credit_costs[{name!r}] must be a finite number >= 0")
        self._ceiling = check_ceiling(settings.enrichment_max_credits_per_call)
        self._tool_costs = {name.lower(): float(c) for name, c in (tool_costs or {}).items()}
        for name, cost in self._tool_costs.items():
            if not _valid_cost(cost):
                raise EnrichmentConfigError(f"tool_costs[{name!r}] must be a finite number >= 0")
        self._reviewed = frozenset(n.lower() for n in reviewed_tools)

    # --- public API -------------------------------------------------------------------------

    def estimate_cost(self, want: Iterable[str]) -> float:
        return sum(self._costs.get(w, 0.0) for w in dict.fromkeys(want))

    def tool_cost(self, tool_name: str) -> float:
        """Credits one call of this tool is assumed to cost. Unknown => the per-call ceiling:
        a tool we have no price for is treated as paid, at the most we allow."""
        return self._tool_costs.get(tool_name.lower(), self._ceiling)

    async def enrich_contact(
        self, request: EnrichmentRequest, *, allow_paid: bool
    ) -> EnrichmentResult:
        wants = list(dict.fromkeys(request.want))
        if not wants:
            return EnrichmentResult(provider=self.name)  # nothing to look up: no connection
        cost = self.estimate_cost(wants)
        # `is not True`: "false", 1, [] ... are not consent to spend credits.
        if cost > 0 and allow_paid is not True:
            raise PaidLookupRefused(
                f"{'+'.join(wants)} lookup would cost about {cost:g} credit(s) (assumed, "
                "unverified) and allow_paid is not True; nothing was sent"
            )
        if cost > self._ceiling:
            raise PaidLookupRefused(
                f"{'+'.join(wants)} lookup is estimated at {cost:g} credit(s), above the "
                f"per-call ceiling of {self._ceiling:g} (ENRICHMENT_MAX_CREDITS_PER_CALL); "
                "nothing was sent"
            )
        state = _CallState()
        token = self._token_value()
        try:
            async with asyncio.timeout(self._timeout_s):
                async with self._session_factory() as session:
                    listed = list((await session.list_tools()).tools)[:MAX_TOOLS]
                    tools = [_tool_info(t) for t in listed]
                    plan = self.plan(tools, wants)
                    self._check_plan_cost(plan, allow_paid)
                    outcomes = [
                        await self._call(
                            session, tools, tool_name, tool_wants, request, token, state
                        )
                        for tool_name, tool_wants in plan.items()
                    ]
        except EnrichmentError:
            raise
        except TimeoutError as exc:
            raise EnrichmentError(
                f"TamTam MCP timed out after {self._timeout_s:.0f}s" + self._maybe_billed(state)
            ) from exc
        except Exception as exc:
            raise EnrichmentError(
                f"TamTam MCP request failed ({_describe_failure(exc)})" + self._maybe_billed(state)
            ) from exc
        return self._merge(outcomes, wants)

    @staticmethod
    def _maybe_billed(state: _CallState) -> str:
        if not state.sent:
            return ""
        return (
            "; the lookup request had already been sent, so credits may have been spent: "
            "check the TamTam balance before retrying"
        )

    # --- tool discovery (allow-list only) -------------------------------------------------------

    def plan(self, tools: Sequence[ToolInfo], wants: Sequence[str]) -> dict[str, list[str]]:
        """Map each wanted field to an allow-listed discovered tool; group fields served by the
        same tool."""
        plan: dict[str, list[str]] = {}
        for want in wants:
            tool = self._pick_tool(tools, want)
            plan.setdefault(tool.name, []).append(want)
        return plan

    def _pick_tool(self, tools: Sequence[ToolInfo], want: str) -> ToolInfo:
        by_name = {t.name.lower(): t for t in tools}
        for candidate in self._tool_map.get(want, ()):
            tool = by_name.get(candidate.lower())
            if tool is not None:
                self._check_annotations(tool)
                return tool
        allowed = ", ".join(_safe_name(n) for n in self._tool_map.get(want, ())) or "(none)"
        suggested = self._suggest(tools)
        exposed = (
            f"Tools that might fit, suggested only and never called automatically: {suggested}. "
            if suggested
            else f"The server exposes {len(tools)} tool(s), none that looks like a contact lookup. "
        )
        raise EnrichmentError(
            f"No allow-listed TamTam MCP tool found for {want!r} lookups (allowed names: "
            f"{allowed}). {exposed}After checking what a tool does, pin it: "
            f"tool_map={{'{want}': '<tool name>'}} in TamTamMCPEnrichment."
        )

    def _check_annotations(self, tool: ToolInfo) -> None:
        """Defence in depth on top of the allow-list: a server that publishes annotations must
        say the tool is read-only and not destructive."""
        if tool.annotations is None or tool.name.lower() in self._reviewed:
            return
        if tool.annotations.get("destructiveHint") is True:
            raise EnrichmentError(
                f"Tool {_safe_name(tool.name)!r} is marked destructive by the server; refusing "
                "to call it"
            )
        if tool.annotations.get("readOnlyHint") is not True:
            raise EnrichmentError(
                f"Tool {_safe_name(tool.name)!r} is not marked readOnlyHint=true by the server; "
                "refusing to call it. After reviewing what it does, pass its name in "
                "reviewed_tools"
            )

    @staticmethod
    def _suggest(tools: Sequence[ToolInfo]) -> str:
        names = [
            _safe_name(t.name)
            for t in tools
            if any(w in t.name.lower() or w in t.description.lower() for w in _SUGGEST_WORDS)
        ]
        return ", ".join(sorted(dict.fromkeys(names))[:MAX_SUGGESTED_NAMES])

    def _check_plan_cost(self, plan: Mapping[str, Sequence[str]], allow_paid: bool) -> None:
        """Refuse before any tool is called when the chosen tools cost more than we allow."""
        estimate = sum(self.tool_cost(name) for name in plan)
        if estimate > 0 and allow_paid is not True:
            raise PaidLookupRefused("the chosen tool(s) spend credits and allow_paid is not True")
        if estimate > self._ceiling:
            raise PaidLookupRefused(
                f"the chosen tool(s) are estimated at {estimate:g} credit(s) in total, above the "
                f"per-call ceiling of {self._ceiling:g}; nothing was called (set tool_costs if the "
                "real prices are lower)"
            )

    # --- calling ------------------------------------------------------------------------------

    @staticmethod
    def build_arguments(
        tool: ToolInfo, request: EnrichmentRequest, wants: Sequence[str]
    ) -> dict[str, Any]:
        """Fill the tool's advertised input schema from the request (assumed naming)."""
        props: dict[str, Any] = tool.input_schema.get("properties") or {}
        if not props:  # no schema advertised: send our canonical names
            args: dict[str, Any] = {
                "full_name": request.full_name,
                "company_name": request.company_name,
                "want": list(wants),
            }
            if request.company_domain:
                args["company_domain"] = request.company_domain
            return args

        args = {}

        def put(names: Sequence[str], value: Any) -> bool:
            for n in names:
                if n in props:
                    args[n] = value
                    return True
            return False

        if not put(
            ("full_name", "fullName", "name", "person_name", "contact_name"), request.full_name
        ):
            first, _, last = request.full_name.strip().partition(" ")
            put(("first_name", "firstName"), first)
            put(("last_name", "lastName"), last or first)
        put(
            ("company_name", "company", "organization", "organisation", "employer"),
            request.company_name,
        )
        if request.company_domain:
            put(
                ("company_domain", "domain", "website", "company_website", "company_url"),
                request.company_domain,
            )
        for slot in ("want", "fields", "reveal", "enrich_fields", "data_types", "include", "types"):
            if slot in props:
                value = _selector_value(props[slot], wants)
                if value is not _SKIP:
                    args[slot] = value
                break
        missing = [r for r in tool.input_schema.get("required", []) if r not in args]
        if missing:
            raise EnrichmentError(
                f"Tool {_safe_name(tool.name)!r} requires argument(s) "
                f"{sorted(_safe_name(str(m)) for m in missing)} that this client "
                "does not know how to fill; extend TamTamMCPEnrichment.build_arguments"
            )
        return args

    async def _call(
        self,
        session: Any,
        tools: Sequence[ToolInfo],
        tool_name: str,
        wants: Sequence[str],
        request: EnrichmentRequest,
        token: str | None,
        state: _CallState,
    ) -> _Outcome:
        tool = next(t for t in tools if t.name == tool_name)
        args = self.build_arguments(tool, request, wants)
        state.sent = True
        result = await session.call_tool(tool_name, args)
        # From here on the call has been billed (or may have been). Nothing below may raise past
        # the spend record: a result we cannot parse still returns the assumed cost (SR2-10).
        estimate = self.tool_cost(tool_name)
        try:
            payload = _payload(result)
            if _attr(result, "is_error", "isError", default=False):
                text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
                raise EnrichmentError(
                    f"Tool {_safe_name(tool_name)!r} returned an error: "
                    f"{safe_server_text(text, _names_to_mask(request, token))}"
                )
            found = parse_contact(payload)
        except (RecursionError, ValueError, TypeError, MemoryError, OverflowError) as exc:
            log.warning("tamtam_mcp tool=%s result could not be parsed (%s)", tool_name,
                        type(exc).__name__)  # fmt: skip
            return _Outcome(tool_name, list(wants), Found(), estimate, type(exc).__name__)
        log.info(
            "tamtam_mcp tool=%s wanted=%s found_email=%s found_mobile=%s",
            tool_name,
            list(wants),
            found.email is not None,
            found.mobile is not None,
        )
        return _Outcome(tool_name, list(wants), found, estimate)

    def _merge(self, outcomes: Sequence[_Outcome], wants: Sequence[str]) -> EnrichmentResult:
        email = next(
            (o.found.email for o in outcomes if "email" in o.wants and o.found.email), None
        )
        mobile = next(
            (o.found.mobile for o in outcomes if "mobile" in o.wants and o.found.mobile), None
        )
        notes: list[str] = []
        total = 0.0
        for o in outcomes:
            credits, note = self._outcome_credits(o)
            total += credits
            notes += note
        if total > self._ceiling and not any("ceiling" in n for n in notes):
            notes.append(f"total credits {total:g} exceed the per-call ceiling {self._ceiling:g}")
        for note in notes:
            log.warning("tamtam_mcp anomaly: %s", note)
        return EnrichmentResult(
            provider=self.name,
            email=email if "email" in wants else None,
            mobile=mobile if "mobile" in wants else None,
            credits_used=total,
            source=next((o.found.source for o in outcomes if o.found.source), None),
            raw_tool=", ".join(dict.fromkeys(o.tool for o in outcomes)),
            anomalous=bool(notes),
            notes=notes,
        )

    def _outcome_credits(self, o: _Outcome) -> tuple[float, list[str]]:
        """(credits to record, anomaly notes) for one tool call. Never negative, never NaN."""
        tool = _safe_name(o.tool)
        if o.parse_failure is not None:
            return o.estimate, [
                f"{tool}: result could not be parsed ({o.parse_failure}); recorded the assumed "
                f"{o.estimate:g} credit(s)"
            ]
        reported = o.found.credits
        if reported is None:  # assumed: charged per field actually delivered
            delivered = (self._costs.get("email", 0.0) if o.found.email else 0.0) + (
                self._costs.get("mobile", 0.0) if o.found.mobile else 0.0
            )
            return delivered, []
        if not math.isfinite(reported) or reported < 0:
            return o.estimate, [
                f"{tool}: the server reported an invalid credit figure; recorded the assumed "
                f"{o.estimate:g} credit(s)"
            ]
        if reported > self._ceiling:
            return reported, [
                f"{tool}: the server reported {reported:g} credit(s), above the per-call "
                f"ceiling of {self._ceiling:g}"
            ]
        return reported, []

    # --- connection ---------------------------------------------------------------------------

    def _token_value(self) -> str | None:
        if self._token is not None:
            return self._token or None
        secret = self._settings.tamtam_mcp_token
        return secret.get_secret_value() if secret is not None and len(secret) else None

    def _default_session(self) -> AbstractAsyncContextManager[Any]:
        token = self._token_value()
        if token is None:
            raise EnrichmentConfigError(
                "TAMTAM_MCP_TOKEN is not set. Sign in to TamTam with an OAuth-capable MCP client "
                "and put the access token in backend/.env (see app/enrichment/tamtam_mcp.py)."
            )
        return open_http_session(self._settings.tamtam_mcp_url, token)


# --- argument values -----------------------------------------------------------------------------


class _Skip:
    """Marker: leave the slot unfilled."""


_SKIP = _Skip()


def _selector_value(prop: Any, wants: Sequence[str]) -> Any:
    """The value for a 'which fields' slot, shaped by the slot's declared type (SR2-04): a list
    for an array (or an undeclared type), a comma list for a string, and NOTHING for a boolean
    like `reveal`, where a truthy list would silently mean "reveal everything"."""
    schema = prop if isinstance(prop, dict) else {}
    items = schema.get("items")
    enum = items.get("enum") if isinstance(items, dict) else schema.get("enum")
    values = [w for w in wants if not isinstance(enum, list) or w in enum]
    if not values:
        return _SKIP
    declared = schema.get("type")
    if declared in (None, "array"):
        return values
    if declared == "string":
        return ",".join(values)
    return _SKIP


# --- result parsing (defensive: the real payload shape is unknown) ---------------------


@dataclass(frozen=True)
class Found:
    email: str | None = None
    mobile: str | None = None
    credits: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class _Outcome:
    tool: str
    wants: list[str]
    found: Found
    estimate: float = 0.0
    parse_failure: str | None = None


def _payload(result: Any) -> Any:
    """The tool result as JSON-like data, or its text. Size-capped BEFORE anything is parsed;
    deep nesting raises RecursionError, which the caller turns into an `anomalous` result."""
    structured = _attr(result, "structured_content", "structuredContent", default=None)
    if structured:
        return structured
    texts = [
        b.text
        for b in (_attr(result, "content", default=None) or [])
        if _attr(b, "type", default=None) == "text" and isinstance(_attr(b, "text"), str)
    ]
    if sum(len(t) for t in texts) > MAX_RESULT_CHARS:
        raise ValueError("tool result is larger than the size cap")
    joined = "\n".join(texts)
    for candidate in (joined, *texts):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return joined


_CREDIT_USED_KEYS = (
    "credits_used", "credits_charged", "credit_cost", "credits_spent", "credits_consumed",
)  # fmt: skip
# `credits`, `credits_remaining`, `balance`... are deliberately NOT here: they are usually the
# account balance, and counting one as spend would corrupt any budget built on credits_used.
_USED_CHILD_KEYS = frozenset({"used", "spent", "charged", "cost", "consumed"})
_SOURCE_KEYS = ("source", "data_source", "provider")


def _walk(node: Any, key: str = "", depth: int = 0, budget: list[int] | None = None):
    """Yield (lowercased key, scalar) for every scalar in a JSON-like structure.

    Strings that themselves contain JSON are unwrapped: MCP servers that return a `str` from a
    tool often surface it as {"result": "<json text>"} in structured content. Bounded in depth
    and node count: a hostile structure is truncated, never recursed to exhaustion.
    """
    if budget is None:
        budget = [MAX_WALK_NODES]
    if depth > MAX_JSON_DEPTH or budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, Mapping):
        kind = str(node.get("type", node.get("label", ""))).lower()[:32]
        for k, v in node.items():
            hint = str(k).lower()[:64]
            if hint in ("value", "number", "address") and kind:
                hint = f"{kind}_{hint}"  # {"type": "mobile", "value": "+33..."}
            elif "credit" in key and hint in _USED_CHILD_KEYS:
                hint = "credits_used"  # {"credits": {"used": 1, "remaining": 99}}
            yield from _walk(v, hint, depth + 1, budget)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _walk(item, key, depth + 1, budget)
    elif isinstance(node, str) and depth < 3 and node.lstrip()[:1] in ("{", "["):
        try:
            inner = json.loads(node[:MAX_RESULT_CHARS])
        except (ValueError, RecursionError):
            yield key, node[:MAX_LEAF_CHARS]
        else:
            yield from _walk(inner, key, depth + 1, budget)
    elif isinstance(node, str):
        yield key, node[:MAX_LEAF_CHARS]
    else:
        yield key, node


def parse_contact(payload: Any) -> Found:
    """Best-effort extraction of email / mobile / credits from an unknown tool result."""
    emails: list[tuple[int, str]] = []
    mobiles: list[tuple[int, str]] = []
    credits: float | None = None
    source: str | None = None
    for key, value in _walk(payload):
        if isinstance(value, str):
            text = value.strip()
            if "email" in key or "mail" in key:
                m = _EMAIL_RE.fullmatch(text) or _EMAIL_RE.search(text)
                if m:
                    emails.append((0 if "work" in key or "professional" in key else 1, m.group()))
            elif any(w in key for w in ("mobile", "cell", "phone", "tel")):
                digits = re.sub(r"\D", "", text)
                if _PHONE_RE.fullmatch(text) and 8 <= len(digits) <= 15:
                    explicit = "mobile" in key or "cell" in key
                    mobiles.append((0 if explicit else 1, text))
            elif key in _SOURCE_KEYS and source is None and len(text) <= 80:
                source = _strip_control(text).strip()[:MAX_SOURCE_CHARS] or None  # SR5-07
            elif _EMAIL_RE.fullmatch(text):  # e.g. {"label": "work", "value": "a@b.c"}
                emails.append((2, text))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            if key in _CREDIT_USED_KEYS and credits is None:
                credits = float(value)
    if not emails and not mobiles and isinstance(payload, str):  # plain-text result
        head = payload[:MAX_RESULT_CHARS]
        em = _EMAIL_RE.search(head)
        ph = _PHONE_RE.search(head)
        return Found(email=em.group() if em else None, mobile=ph.group() if ph else None)
    return Found(
        email=min(emails)[1] if emails else None,
        mobile=min(mobiles)[1] if mobiles else None,
        credits=credits,
        source=source,
    )
